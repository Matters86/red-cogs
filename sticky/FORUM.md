# Sticky

Hält eine Nachricht am **unteren Ende eines Kanals** fest: Sobald jemand schreibt, löscht der
Bot die alte Sticky und postet sie unten neu. Mit Text- oder Embed-Modus, optionalem Webhook
(eigener Name/Avatar), Platzhaltern, Cooldown gegen Spam und kompletter Konfiguration über das
Web-Dashboard.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs sticky
[p]load sticky
```
Bot-Rechte im Kanal: **Nachrichten senden** + **Nachrichten verwalten** (Webhook-Modus zusätzlich **Webhooks verwalten**).

## Schnellstart
```
[p]sticky set #regeln Willkommen! Bitte lies die Regeln.
```
Die Nachricht wandert ab sofort automatisch immer ans Ende von `#regeln`.

## Platzhalter
`{membercount}` (Mitgliederzahl), `{servername}` (Server), `{channel}` (Kanal-Erwähnung), `{channelname}` (Kanalname).

## Befehle – Stickies (Mod)
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]sticky set <channel> <text>` | Text-Sticky setzen. | Mod / „Nachrichten verwalten" |
| `[p]sticky embed <channel> <text>` | Embed-Sticky setzen (Titel/Farbe/Bild im Dashboard). | Mod / „Nachrichten verwalten" |
| `[p]sticky remove <channel>` | Sticky entfernen. | Mod / „Nachrichten verwalten" |
| `[p]sticky toggle <channel>` | An-/ausschalten (ohne Löschen). | Mod / „Nachrichten verwalten" |
| `[p]sticky refresh <channel>` | Sofort neu posten (umgeht Cooldown). | Mod / „Nachrichten verwalten" |
| `[p]sticky show <channel>` | Konfiguration anzeigen. | Mod / „Nachrichten verwalten" |
| `[p]sticky list` | Alle Stickies des Servers auflisten. | Mod / „Nachrichten verwalten" |

## Befehle – Einstellungen (Admin)
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]sticky cooldown <sekunden>` | Cooldown setzen (0–3600). | Admin / „Server verwalten" |
| `[p]sticky ignorebots <true/false>` | Nachrichten anderer Bots (nicht) auslösen lassen. | Admin / „Server verwalten" |
| `[p]sticky language <de/en>` | Sprache der Bot-Antworten. | Admin / „Server verwalten" |
| `[p]sticky settings` | Aktuelle Einstellungen anzeigen. | Admin / „Server verwalten" |

Gibt es auch als Slash-Befehle (`/sticky …`).

## Dashboard
Mit geladenem `webcore` erscheint der Tab **Sticky**: Übersicht aller Stickies, pro Kanal eine
Sticky anlegen/bearbeiten (Text oder Embed mit Titel/Farbe/Bild/Footer), Webhook-Modus samt
Name/Avatar sowie Sprache, Cooldown und „andere Bots ignorieren" – alles per Formular.

## Hinweise
- Kein Message-Content-Intent nötig (reagiert nur auf das Ereignis, nicht den Inhalt).
- Cooldown `0` = sofort (kann in aktiven Kanälen flackern); ein paar Sekunden sind empfohlen.
- Nach einem Neustart wird die Sticky bei der nächsten Nachricht sauber neu verankert.
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: `webcore` ist geladen und eingerichtet.
