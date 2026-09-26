# Welcome

Begrüßt **neue Mitglieder** mit einer Nachricht (Text oder Embed), optional mit einem
**Willkommensbild** und einer **DM**, und **verabschiedet** Mitglieder, die den Server verlassen.

Highlights:

- **Willkommen & Abschied** mit je eigenem Kanal, als **Text oder Embed** (Titel, Text, Farbe, Bild-URL).
- **Platzhalter:** `{user}` (Erwähnung), `{name}`, `{server}`, `{count}` (Mitgliederzahl), `{created}` (Kontoalter).
  Unbekannte `{…}` bleiben unverändert stehen – kein Absturz durch Tippfehler.
- **Willkommensbild** (Pillow): Banner mit rundem Avatar, Name und „Mitglied #N“ auf Farbverlauf oder
  eigenem Hintergrundbild (https-URL). Gerendert im Hintergrund-Thread, Avatar mit Timeout und Größenlimit.
- **Willkommens-DM** – geschlossene DMs werden still übersprungen.
- **Ping-Schutz:** gepingt wird höchstens das neue Mitglied (abschaltbar), nie `@everyone`, `@here` oder Rollen.
- **Bots ignorieren** (Schalter, Standard an).
- **Deutsch/Englisch** für Standardtexte und Antworten.
- **Dashboard-Seite „Willkommen“** mit Live-Vorschau des Bildes und „Testnachricht posten“.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs welcome
[p]load welcome
```

Voraussetzungen: **Server-Mitglieder-Intent** (Members Intent) aktiv; im Zielkanal die Rechte
**Nachrichten senden**, für Embeds **Links einbetten**, für das Bild **Dateien anhängen**.
Abhängigkeit: `Pillow` (wird bei `[p]cog install` mitinstalliert).

## Schnellstart

```
[p]welcomeset channel welcome #willkommen
[p]welcomeset toggle welcome on
[p]welcomeset toggle card on
[p]welcomeset test
```

## Befehle

Alle Befehle: **Server verwalten** (oder Admin/Bot-Owner). Text- und Slash-Befehle.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]welcomeset channel <welcome\|leave> [#kanal]` | Kanal für Willkommen/Abschied setzen (ohne Kanal = entfernen) | Server verwalten |
| `[p]welcomeset toggle <welcome\|leave\|dm\|card> [on\|off]` | Willkommen, Abschied, DM oder Bild ein-/ausschalten | Server verwalten |
| `[p]welcomeset message <welcome\|leave\|dm> [text]` | Eigenen Text setzen (ohne Text = Standardtext) | Server verwalten |
| `[p]welcomeset mode <welcome\|leave\|dm> <text\|embed>` | Darstellung als Text oder Embed | Server verwalten |
| `[p]welcomeset title <welcome\|leave\|dm> [titel]` | Embed-Titel (ohne Text = Standard) | Server verwalten |
| `[p]welcomeset color <welcome\|leave\|dm> <#hex>` | Embed-Farbe | Server verwalten |
| `[p]welcomeset image <welcome\|leave\|dm> [https-url]` | Bild im Embed (ohne URL = entfernen) | Server verwalten |
| `[p]welcomeset ping <on\|off>` | Neues Mitglied in der Willkommensnachricht anpingen | Server verwalten |
| `[p]welcomeset bots <on\|off>` | Bots ignorieren | Server verwalten |
| `[p]welcomeset cardcolors <hintergrund> <akzent> [text]` | Farben des Willkommensbildes | Server verwalten |
| `[p]welcomeset cardbackground [https-url]` | Hintergrundbild des Willkommensbildes (ohne URL = Farbverlauf) | Server verwalten |
| `[p]welcomeset cardheadline [text]` | Überschrift des Bildes (ohne Text = „WILLKOMMEN“) | Server verwalten |
| `[p]welcomeset language <de\|en>` | Sprache der Standardtexte und Antworten | Server verwalten |
| `[p]welcomeset test [welcome\|leave\|dm]` | Zeigt die Nachricht mit dir als Beispiel (hier im Kanal bzw. als DM) | Server verwalten |
| `[p]welcomeset settings` | Aktuelle Einstellungen anzeigen | Server verwalten |

## Platzhalter

| Platzhalter | Ergebnis |
|---|---|
| `{user}` | Erwähnung des Mitglieds (pingt nur, wenn „anpingen“ an ist) |
| `{name}` | Anzeigename |
| `{server}` | Servername |
| `{count}` | Mitgliederzahl (beim Beitritt = Nummer des neuen Mitglieds) |
| `{created}` | Kontoalter, z. B. „3 Jahre“ |

## Willkommensbild

1000 × 400 px, runder Avatar mit Ring, Überschrift, Name und „Mitglied #N · Server“. Hintergrund:
Farbverlauf aus Hintergrund- und Akzentfarbe oder ein Bild per **https-URL** (PNG/JPEG/WebP/GIF,
max. 8 MB, max. 6000 px je Seite; wird zugeschnitten und abgedunkelt). Aus Sicherheitsgründen lädt der
Bot nur **öffentliche** Adressen auf Port 443 – Adressen im Heimnetz/NAS (z. B. `192.168.…`, `localhost`)
werden abgelehnt. Geladene Hintergründe werden eine Stunde zwischengespeichert. Schlägt das Laden fehl,
nutzt das Bild den Farbverlauf. Im Embed-Modus erscheint das Bild als großes Embed-Bild, sonst als Anhang.

## Dashboard

Seite **Willkommen** (Icon Tür) im WebCore-Dashboard, Server über den Wechsler in der Kopfzeile:

- **Kennzahlen:** Status von Willkommen, Abschied, DM, Bild und die Mitgliederzahl.
- **Reiter Willkommen / Abschied / DM:** Schalter, Kanal, Darstellung, Text, Embed-Titel/-Farbe/-Bild,
  unter Willkommen zusätzlich Ping, Bots ignorieren und Sprache. Unten eine **Beispiel-Vorschau** der
  gespeicherten Nachricht mit dir als Mitglied. Hinweise, wenn Kanal oder Bot-Rechte fehlen.
- **Reiter Bild:** Farben, Überschrift, Hintergrundbild-URL mit **Live-Vorschau** (aktualisiert sich beim
  Tippen, zeigt auch, warum ein Hintergrundbild nicht geladen werden konnte).
- **„Testnachricht posten“** speichert und postet die Nachricht mit dir als Beispiel in den eingestellten
  Kanal (DM-Reiter: „Test-DM an mich senden“). Gepingt wird beim Test niemand.

Rechte: **Ansehen** zeigt alles schreibgeschützt (Live-Vorschau nur mit gespeicherten Werten);
**Bearbeiten** erlaubt Speichern, Tests und die Live-Vorschau mit ungespeicherten Werten.

## Datenschutz

Es werden keine personenbezogenen Daten gespeichert. Avatare werden nur kurz im Arbeitsspeicher
zwischengespeichert, um das Bild zu erzeugen.
