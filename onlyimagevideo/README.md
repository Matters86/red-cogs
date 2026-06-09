# OnlyImageVideo

Mehrsprachiger Moderations-Cog für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot): Er macht ausgewählte Kanäle zu **reinen Medien-Kanälen**. Nachrichten ohne Bild, Video oder GIF werden gelöscht; ein kurzer, **selbstlöschender Hinweis** erklärt die Regel.

Ähnlich wie „onlyimage", aber zusätzlich für **Videos und GIFs** – inklusive GIF-Picker-Links (Tenor/Giphy) und direkter Mediendatei-Links.

## Funktionen

- **Nur-Medien-Kanäle** per Allowlist – beliebig viele Kanäle.
- **Threads erben** die Regel automatisch vom übergeordneten Kanal.
- Als gültiges Medium zählen: hochgeladene **Bilder/Videos** (inkl. `.gif`), **Sticker**, **direkte Links** zu Mediendateien und Links von **GIF-/Medien-Diensten** (Tenor, Giphy, Imgur …) – jeweils pro Server abschaltbar.
- **Selbstlöschender Hinweis** beim Entfernen (Dauer einstellbar), abschaltbar für stilles Löschen.
- **Ausnahmen:** Bots/Webhooks (standardmäßig) sowie frei wählbare **Ausnahme-Rollen**.
- Erkennt Medien-Links zuverlässig über URL und Host – unabhängig davon, dass Discord die Linkvorschau erst nach dem Senden nachlädt.
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (`de`, `en`).
- **Dashboard** – komplette Verwaltung im WebCore-Dashboard.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs onlyimagevideo
[p]load onlyimagevideo
```

Damit das Löschen funktioniert, braucht der Bot in den betroffenen Kanälen das Recht **Nachrichten verwalten**.

## Schnellstart

```
[p]oiv add #memes
[p]oiv add #clips
[p]oiv language de
```

Ab sofort werden in `#memes` und `#clips` (und deren Threads) reine Textnachrichten entfernt.

## Befehle

Alle Befehle erfordern „Server verwalten" oder Admin. Gruppe: `[p]oiv` (Alias `[p]onlyimagevideo`); auch als Slash-Befehl `/oiv` verfügbar.

| Befehl | Beschreibung |
|---|---|
| `[p]oiv add <kanal>` | Kanal als Nur-Medien-Kanal markieren |
| `[p]oiv remove <kanal>` | Kanal aus der Liste entfernen |
| `[p]oiv list` | Alle Nur-Medien-Kanäle anzeigen |
| `[p]oiv exemptrole <rolle>` | Ausnahme-Rolle hinzufügen/entfernen (Umschalter) |
| `[p]oiv links` | Links zu Mediendateien als Medium zählen (Umschalter) |
| `[p]oiv gifhosts` | GIF-/Medien-Dienste als Medium zählen (Umschalter) |
| `[p]oiv stickers` | Sticker als Bild zählen (Umschalter) |
| `[p]oiv ignorebots` | Bots/Webhooks ausnehmen (Umschalter) |
| `[p]oiv notify` | Hinweis beim Löschen senden (Umschalter) |
| `[p]oiv language <de\|en>` | Sprache setzen |
| `[p]oiv settings` | Aktuelle Einstellungen anzeigen |
| `[p]oiv dashboard` | Hinweis zur Dashboard-Seite |

Unterstützte Kanaltypen für `add`/`remove`: Text-, Voice- und Forum-Kanäle.

## Was zählt als Medium?

- **Anhänge** mit Bild- oder Video-Inhaltstyp (Fallback über die Dateiendung), inklusive hochgeladener `.gif`.
- **Sticker** (sofern aktiviert).
- **Links auf Mediendateien**, erkannt an der Endung: `.png .jpg .jpeg .webp .gif .gifv .mp4 .webm .mov` u. a. (sofern aktiviert).
- **Links von GIF-/Medien-Diensten** wie `tenor.com`, `giphy.com`, `imgur.com`, `gfycat.com`, `redgifs.com` sowie Discord-CDN-Links (sofern aktiviert).

Eine Nachricht mit Text **und** Medium ist erlaubt; entfernt wird nur reiner Text ohne Medium. Wird eine Medien-Nachricht nachträglich so bearbeitet, dass kein Medium mehr enthalten ist, greift die Regel ebenfalls.

## Dashboard

Die Seite **Nur Medien** erscheint nach dem Laden automatisch im WebCore-Dashboard unter `/cogs/onlyimagevideo`. Dort gibt es:

- Statistik-Kacheln (überwachte Kanäle, Ausnahme-Rollen, gelöschte Nachrichten),
- ein Einstellungs-Formular (Sprache, Kanäle, Ausnahme-Rollen, alle Schalter, Hinweisdauer, Hinweistext-Override),
- eine Übersicht „Funktionsweise", die zeigt, was aktuell als Medium zählt.

## Datenspeicherung

Es werden keine personenbezogenen Daten gespeichert – nur serverbezogene Einstellungen und ein Zähler gelöschter Nachrichten. Inhalte gelöschter Nachrichten werden nicht gespeichert.
