# ServerLayout (Server-Layout)

Speichert das **Layout eines Discord-Servers** – Rollen, Kategorien/Kanäle mit Berechtigungen und die
Server-Einstellungen – und lädt es auf einen **anderen oder denselben** Server. Ideal, um einen zweiten Server gleich
aufzubauen, eine Vorlage zu pflegen oder vor großen Umbauten einen Stand festzuhalten.
Für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot), bedienbar per Befehl oder im WebCore-Dashboard.

> ⚠️ **Wichtig – „Exakt angleichen“ löscht.** In diesem Modus werden Rollen und Kanäle, die **nicht im Layout** stehen,
> **gelöscht**. Nachrichten in gelöschten Kanälen sind **unwiderruflich weg** – die automatische Sicherung stellt nur
> **leere** Kanäle wieder her. Mitglieder verlieren gelöschte Rollen. Deshalb: immer zuerst die Vorschau lesen,
> im Zweifel **„Ergänzen“** nehmen. Angleichen verlangt, dass man den **Server-Namen eintippt**.

## Was ein Layout enthält

| Teil | Inhalt |
|---|---|
| **Rollen** | Name, Farbe, Rechte, „hervorheben“, „erwähnbar“, Reihenfolge, Rechte von `@everyone`. **Keine** Mitglieder-Zuordnung. Verwaltete Rollen (Bots, Integrationen, Server-Booster) stehen nur zur Info drin – sie werden nie angelegt, geändert oder gelöscht. |
| **Kanäle** | Kategorien und Text-, Ankündigungs-, Sprach-, Stage- und Forum-Kanäle: Name, Typ, Kategorie, Reihenfolge, Thema, Slowmode, NSFW, Bitrate/Nutzerlimit/Region/Videoqualität, Thread-Standards, Forum-Tags (Unicode-Emojis), Standard-Ansicht/-Sortierung/-Reaktion, Synchronisierung mit der Kategorie und **alle Berechtigungs-Überschreibungen für Rollen** (per Rollen-Name, `@everyone` gesondert). Überschreibungen für **einzelne Mitglieder** werden nur mitgeschrieben – beim Laden übersprungen und gemeldet. |
| **Einstellungen** | Server-Name, Icon, Banner, Beschreibung, Verifizierungsstufe, Filter für explizite Inhalte, Standard-Benachrichtigungen, AFK-Kanal + Timeout, Systemkanal + Optionen, Regel-/Update-Kanal (Kanäle per Name). Icon/Banner als base64 in der Datei (je höchstens 3 MB). |

**Nicht enthalten:** Nachrichten, Emojis/Sticker, Mitglieder, Bans, Webhooks, Einladungen, Server-Emojis in Forum-Tags.

Beim Speichern und beim Laden lässt sich jeweils wählen, welche Teile (Rollen / Kanäle / Einstellungen) gelten.

## Laden: zwei Modi

- **Ergänzen** – fehlende Rollen/Kategorien/Kanäle werden angelegt, vorhandene gleichnamige angepasst (Farbe, Rechte,
  Überschreibungen, Thema, Reihenfolge …). **Es wird nichts gelöscht**; vorhandene Überschreibungen für andere
  Rollen/Mitglieder bleiben.
- **Exakt angleichen** – wie Ergänzen, zusätzlich werden Rollen, Kategorien und Kanäle **gelöscht**, die nicht im Layout
  stehen (nur in den gewählten Teilen). **Nie gelöscht** werden: `@everyone`, verwaltete Rollen, Rollen über oder auf Höhe
  der höchsten Bot-Rolle, die Rolle des Bots, Regel-/Update-Kanal eines Community-Servers (lässt Discord nicht zu), der
  Kanal, in dem der Befehl läuft, und Kanäle, in denen der Bot keine Rechte hat. Überschreibungen für Mitglieder und
  verwaltete Rollen auf dem Ziel bleiben erhalten.

**Zuordnung per Name:** Rollen per Name (gleichnamige Rollen in ihrer Reihenfolge von unten), Kategorien per Name,
Kanäle per **Name + Typ + Kategorie** (Text und Ankündigung gelten als gleicher Typ). Ein Kanal, der im Layout in
einer anderen Kategorie liegt, wird deshalb neu angelegt (und beim Angleichen der alte gelöscht).

**Ablauf:**
1. **Vorschau (Pflicht):** Liste „wird angelegt / geändert (was genau) / gelöscht / übersprungen (warum)“ mit Zahlen und
   Warnungen. Fehlen dem Bot *Rollen verwalten*, *Kanäle verwalten* oder *Server verwalten*, ist Anwenden gesperrt.
2. **Bestätigen** – beim Angleichen den Server-Namen eintippen. Hat sich der Server seit der Vorschau verändert, wird
   abgelehnt und man sieht die Vorschau neu.
3. **Automatische Sicherung:** Vor jedem Laden speichert der Cog den aktuellen Stand des Ziel-Servers als Layout
   „Automatisch vor dem Laden – <Datum>“. Damit kann man zurück (Laden im Modus Angleichen). Es bleiben die letzten
   **10** automatischen Sicherungen je Server.
4. **Ausführung im Hintergrund** (je Server höchstens ein Vorgang gleichzeitig) in dieser Reihenfolge: Rollen →
   Rollen-Reihenfolge (in Blöcken) → Kategorien → Kanäle mit Überschreibungen → Kanal-Reihenfolge →
   Server-Einstellungen → **Löschungen zuletzt**. Fehler eines Schritts werden protokolliert, der Rest läuft weiter.
   Fortschritt und Abbrechen im Dashboard bzw. per `[p]layout status` / `[p]layout cancel`, am Ende ein Bericht.
5. Alle Änderungen tragen im Discord-Audit-Log den Grund „Server-Layout ‚<name>‘ geladen von <user>“.

## Grenzen von Discord (werden vorher geprüft und gemeldet)

- Der Bot kann nur **Rechte vergeben, die er selbst hat** (außer mit Administrator). Solche Rechte werden bei Rollen und
  Überschreibungen weggelassen, nicht steuerbare Rechte bleiben wie sie sind – die Vorschau warnt.
- Der Bot kann nur **Rollen unter seiner höchsten Rolle** ändern, sortieren oder löschen. Rollen darüber werden
  übersprungen; neue Rollen landen immer unter der Bot-Rolle.
- **Community-Funktionen:** Ohne Community legt der Cog Ankündigungs-Kanäle als Text- und Stage-Kanäle als
  Sprachkanäle an; Regel-/Update-Kanal und Beschreibung werden übersprungen. Community selbst wird nie eingeschaltet.
- **Boost-Stufe:** Banner nur mit Boost-Stufe 2 (sonst übersprungen), animiertes Icon/Banner nur mit passender Stufe,
  Bitrate wird auf das Limit des Ziel-Servers begrenzt.
- **Limits:** höchstens 250 Rollen und 500 Kanäle (inkl. Kategorien) – die Vorschau warnt, wenn es mehr würden.
- **Rate-Limits:** discord.py wartet selbst; bei vielen Schritten macht der Cog zusätzlich kleine Pausen. Große Server
  brauchen daher einige Minuten.
- Gelöschte Kanäle und Nachrichten lassen sich **nicht** wiederherstellen.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) (für das Dashboard).

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs serverlayout
[p]load serverlayout
```

## Befehle

Gruppe `[p]layout`. Teile: `rollen`, `kanäle`, `einstellungen` (kommagetrennt, oder `alle`; englisch `roles`,
`channels`, `settings`). Modus: `ergänzen` (Standard) oder `angleichen`. Namen mit Leerzeichen gehen direkt,
Namen, die wie ein Schlüsselwort heißen, in Anführungszeichen.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]layout save <name> [teile]` | Layout dieses Servers speichern (ohne Teile: alle) | Administrator dieses Servers |
| `[p]layout list` | Gespeicherte Layouts (Admins sehen nur Layouts ihres Servers) | Administrator |
| `[p]layout info <name>` | Details zu einem Layout | Administrator (eigener Server) |
| `[p]layout export <name>` | Layout als JSON-Datei senden | Administrator (eigener Server) |
| `[p]layout status` | Fortschritt bzw. letzter Bericht auf diesem Server | Administrator |
| `[p]layout preview <name> [ergänzen\|angleichen] [teile]` | Vorschau für diesen Server | Bot-Owner |
| `[p]layout load <name> [ergänzen\|angleichen] [teile]` | Laden mit Vorschau + Button „Laden“; beim Angleichen Server-Namen im Fenster eintippen (nur Text-Befehl) | Bot-Owner |
| `[p]layout import [name]` | Layout-Datei als **Anhang** importieren, höchstens 8 MB (nur Text-Befehl) | Bot-Owner |
| `[p]layout rename "<name>" <neuer name>` | Layout umbenennen | Bot-Owner |
| `[p]layout delete <name>` | Layout löschen | Bot-Owner |
| `[p]layout cancel` | Laufenden Ladevorgang abbrechen (der laufende Schritt wird beendet) | Bot-Owner |
| `[p]layout language <de\|en>` | Sprache der Bot-Antworten | Administrator |

Der Bot-Owner hat immer alle Rechte. Beispiel:
```
[p]layout save Grundgerüst
[p]layout preview Grundgerüst angleichen rollen,kanäle
[p]layout load Grundgerüst ergänzen
```

## Dashboard

Seite **Server-Layout** (`/cogs/serverlayout`, Icon Diagramm). **Nur für den Bot-Owner** (bzw. Allowlist mit voller
Sicht): Team-Mitglieder mit Seiten-Recht und Server-Admins sehen nur einen Hinweis, alle Aktionen werden serverseitig
abgelehnt. Es gibt kein Tagesgeschäft („Bedienen“ wirkt wie „Ansehen“).
Ziel-Server ist der **globale Server-Wechsler** oben rechts, Quelle ist ein gespeichertes Layout.

- **Layouts** – Tabelle (Name, Quelle, Datum, Teile, Größe) mit *Vorschau/Laden*, *Herunterladen*, *Löschen*
  (mit Bestätigung) und *Umbenennen*.
- **Speichern** – den gewählten Server mit Teile-Auswahl speichern.
- **Hochladen** – Layout-Datei (JSON) hochladen; streng geprüft, unbekannte Felder werden ignoriert. Über das
  Dashboard gilt das Upload-Limit von WebCore (Standard knapp **1 MB**, Hinweis auf der Seite, zu große Dateien werden
  schon im Browser abgefangen) – größere Dateien (bis 8 MB, z. B. mit Banner) per `[p]layout import`.
- **Laden** – Layout, Modus und Teile wählen → **Vorschau** (Zahlen, Warnungen, Tabellen je Bereich) → **Jetzt laden**
  (beim Angleichen Server-Namen eintippen).
- **Verlauf** – laufender Vorgang mit Fortschrittsbalken (aktualisiert sich alle 2 s, ohne JavaScript per Neuladen) und
  *Abbrechen*; darunter die letzten 10 Berichte mit Protokoll.

## Speicherung & Datenschutz

Layouts liegen als JSON-Dateien im Datenordner des Cogs (`…/cogs/ServerLayout/layouts/<id>.json`), in Reds Config
nur ein kleines Verzeichnis (Name, Quelle, Datum, Ersteller-ID, Teile, Größe) und die letzten Berichte je Server.

```json
{"format": "red-serverlayout", "version": 1, "name": "Grundgerüst", "created": "2026-09-30T12:00:00+00:00",
 "creator_id": 1, "source": {"guild_id": 1000, "guild_name": "Matters Community", "premium_tier": 2, "community": true},
 "parts": ["roles", "channels", "settings"], "everyone": {"permissions": 104324673},
 "roles": [{"name": "Gast", "color": 10070709, "permissions": 0, "hoist": false, "mentionable": false, "managed": false}],
 "categories": [{"name": "Info", "overwrites": [{"type": "everyone", "allow": 0, "deny": 2048}]}],
 "channels": [{"name": "regeln", "type": "text", "category": 0, "topic": "…", "overwrites": [], "…": "…"}],
 "settings": {"name": "Matters Community", "afk_channel": {"group": "voice", "name": "AFK", "category": "Voice", "n": 0},
              "icon": {"mime": "image/png", "data": "<base64>"}, "…": "…"}}
```

`red_delete_data_for_user` setzt Ersteller-/Nutzer-IDs auf 0 und entfernt mitgeschriebene
Mitglieder-Überschreibungen dieser Person aus allen Layout-Dateien.
