# Welcome

Begrüßt **neue Mitglieder** mit Nachricht (Text oder Embed), optionalem **Willkommensbild**
(runder Avatar, Name, „Mitglied #N“) und **DM** – und **verabschiedet** Mitglieder beim Verlassen.
Platzhalter `{user}` `{name}` `{server}` `{count}` `{created}`, Ping nur für das neue Mitglied,
Bots ignorieren, Deutsch/Englisch. Komplett über das Web-Dashboard einstellbar – mit Live-Vorschau des Bildes.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs welcome
[p]load welcome
```
Bot-Rechte im Kanal: **Nachrichten senden**, **Links einbetten** (Embed), **Dateien anhängen** (Bild).
Der **Mitglieder-Intent** muss aktiv sein.

## Schnellstart
```
[p]welcomeset channel welcome #willkommen
[p]welcomeset toggle welcome on
[p]welcomeset toggle card on
[p]welcomeset test
```

## Befehle
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]welcomeset channel <welcome\|leave> [#kanal]` | Kanal für Willkommen/Abschied | Server verwalten |
| `[p]welcomeset toggle <welcome\|leave\|dm\|card> [on\|off]` | Willkommen/Abschied/DM/Bild an/aus | Server verwalten |
| `[p]welcomeset message <welcome\|leave\|dm> [text]` | Eigener Text (leer = Standard) | Server verwalten |
| `[p]welcomeset mode <welcome\|leave\|dm> <text\|embed>` | Text oder Embed | Server verwalten |
| `[p]welcomeset title <welcome\|leave\|dm> [titel]` | Embed-Titel | Server verwalten |
| `[p]welcomeset color <welcome\|leave\|dm> <#hex>` | Embed-Farbe | Server verwalten |
| `[p]welcomeset image <welcome\|leave\|dm> [https-url]` | Bild im Embed | Server verwalten |
| `[p]welcomeset ping <on\|off>` | Neues Mitglied anpingen | Server verwalten |
| `[p]welcomeset bots <on\|off>` | Bots ignorieren | Server verwalten |
| `[p]welcomeset cardcolors <hintergrund> <akzent> [text]` | Farben des Bildes | Server verwalten |
| `[p]welcomeset cardbackground [https-url]` | Hintergrundbild (leer = Farbverlauf) | Server verwalten |
| `[p]welcomeset cardheadline [text]` | Überschrift des Bildes | Server verwalten |
| `[p]welcomeset language <de\|en>` | Sprache | Server verwalten |
| `[p]welcomeset test [welcome\|leave\|dm]` | Testnachricht mit dir als Beispiel | Server verwalten |
| `[p]welcomeset settings` | Einstellungen anzeigen | Server verwalten |

## Dashboard
Seite **Willkommen**: Reiter **Willkommen**, **Abschied**, **DM** (Kanal, Text/Embed, Beispiel-Vorschau)
und **Bild** (Farben, Überschrift, Hintergrund-URL mit **Live-Vorschau**). Knopf **„Testnachricht posten“**
postet mit dir als Beispiel in den eingestellten Kanal.
