# 🖼️ OnlyImageVideo

Mehrsprachiger Moderations-Cog für Red: Er macht ausgewählte Kanäle zu **reinen Medien-Kanälen** – Nachrichten ohne Bild, Video oder GIF werden gelöscht, ein kurzer **selbstlöschender Hinweis** erklärt die Regel. Ähnlich „onlyimage", aber zusätzlich für **Videos und GIFs** inklusive GIF-Picker-Links (Tenor/Giphy). **Deutsch ist Standard**, die Sprache ist pro Server umschaltbar. Komplette Verwaltung auch über das **WebCore-Dashboard**.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs onlyimagevideo
[p]load onlyimagevideo
```
Voraussetzung: der Cog `webcore` ist installiert. Der Bot braucht in den betroffenen Kanälen das Recht **Nachrichten verwalten**.

**Funktionen**
- Beliebig viele Nur-Medien-Kanäle (Allowlist); **Threads erben** die Regel
- Gültig: Bild-/Video-Uploads (inkl. `.gif`), **Sticker**, direkte Mediendatei-Links und **Tenor/Giphy/Imgur**-Links – jeweils abschaltbar
- Selbstlöschender Hinweis (Dauer einstellbar) oder stilles Löschen
- Ausnahmen: Bots/Webhooks (Standard) + frei wählbare Ausnahme-Rollen
- Greift auch, wenn eine Medien-Nachricht später medienfrei bearbeitet wird

**Befehle** – alle erfordern „Server verwalten"/Admin. Gruppe `[p]oiv` (Alias `[p]onlyimagevideo`), auch als `/oiv`.

| Befehl | Beschreibung |
|---|---|
| `[p]oiv add <kanal>` | Kanal als Nur-Medien-Kanal markieren. |
| `[p]oiv remove <kanal>` | Kanal aus der Liste entfernen. |
| `[p]oiv list` | Alle Nur-Medien-Kanäle anzeigen. |
| `[p]oiv exemptrole <rolle>` | Ausnahme-Rolle hinzufügen/entfernen. |
| `[p]oiv links` | Mediendatei-Links als Medium zählen (Umschalter). |
| `[p]oiv gifhosts` | GIF-/Medien-Dienste als Medium zählen (Umschalter). |
| `[p]oiv stickers` | Sticker als Bild zählen (Umschalter). |
| `[p]oiv ignorebots` | Bots/Webhooks ausnehmen (Umschalter). |
| `[p]oiv notify` | Hinweis beim Löschen senden (Umschalter). |
| `[p]oiv language <de\|en>` | Sprache setzen. |
| `[p]oiv settings` | Aktuelle Einstellungen anzeigen. |
| `[p]oiv dashboard` | Hinweis zur Dashboard-Seite. |

Unterstützte Kanaltypen: Text-, Voice- und Forum-Kanäle.

**Beispiel**
```
[p]oiv add #memes
[p]oiv add #clips
```
In `#memes` und `#clips` (samt Threads) werden ab sofort reine Textnachrichten entfernt. Erlaubt bleibt jede Nachricht mit Bild, Video, GIF, Sticker oder einem entsprechenden Link.

Verwaltung komplett auch im **WebCore-Dashboard** möglich (Seite „Nur Medien" unter `/cogs/onlyimagevideo`): Kanäle, Ausnahme-Rollen, alle Schalter, Hinweistext und eine Übersicht „Funktionsweise".
