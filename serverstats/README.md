# ServerStats

**Server-Statistik ohne Personendaten:** Beitritte, Abgänge, Mitgliederzahl, Nachrichten je Kanal und
Voice-Zeit je Kanal – pro Tag gezählt, im Dashboard als Kennzahlen und Diagramme (7/30/90 Tage),
mit Top-10-Kanälen und CSV-Export. Kurzübersicht in Discord mit `[p]stats`.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs serverstats
[p]load serverstats
```
Voraussetzungen: **Members-Intent** (Beitritte/Abgänge). Das Message-Content-Intent ist **nicht** nötig – gezählt
wird nur, *dass* eine Nachricht geschrieben wurde. Für Voice-Zeit das Voice-States-Intent (Standard in Red).

## Was gezählt wird
| Wert | Details |
|---|---|
| Beitritte / Abgänge | pro Tag (Kick/Bann zählt als Abgang) |
| Mitglieder | Stand am Tagesende (letzter Wert des Tages) |
| Nachrichten | je Kanal und Tag; **ohne Bots und Webhooks**, Threads zählen zu ihrem Elternkanal |
| Voice-Zeit | Sekunden je Sprachkanal und Tag; **ohne AFK-Kanal und ohne Bots**; über Mitternacht wird aufgeteilt |

- **Tage = Kalendertage in der Zeitzone des Servers** (IANA-Name, Standard `Europe/Berlin`, einstellbar mit
  `[p]statsset timezone` oder im Dashboard). Ein Tag läuft von Mitternacht bis Mitternacht Ortszeit – auch an den
  Tagen der Zeitumstellung (23 bzw. 25 Stunden); Voice-Sitzungen über Mitternacht werden dort aufgeteilt.
  Diagramme, `[p]stats`, CSV-Export (Spalte `datum`) und das automatische Aufräumen richten sich danach.
- **Umstellung von älteren Versionen:** Bis zu dieser Version wurde in **UTC-Tagen** gezählt. Die vorhandenen Tage
  werden unverändert weiterverwendet (keine Migration nötig) – der Versatz beträgt in `Europe/Berlin` höchstens
  2 Stunden, betroffen sind also nur Zählungen kurz vor bzw. nach Mitternacht. Ein **Zeitzonen-Wechsel gilt ab dann**;
  bereits gezählte Tage werden nicht umgerechnet.
- **Ignorierte Kanäle** (z. B. Bot-Spam) werden weder für Nachrichten noch für Voice gezählt.
- **Schreiblast:** alle Zähler liegen zunächst im Arbeitsspeicher und werden alle **60 Sekunden** (und beim
  Entladen des Cogs) gebündelt gespeichert.
- **Aufbewahrung:** Standard **90 Tage** (7–730), ältere Tage löscht ein Hintergrund-Loop stündlich.

## Befehle
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]stats [tage]` | Kurzübersicht als Embed (Mitglieder, Netto-Wachstum, Nachrichten, Voice-Stunden, aktivste Kanäle; Standard 7 Tage, max. 90) | alle |
| `[p]statsset retention <tage>` | Aufbewahrung in Tagen (7–730, Standard 90) | Server verwalten |
| `[p]statsset ignore <#kanal>` | Kanal nicht mehr zählen – erneut ausführen = wieder zählen | Server verwalten |
| `[p]statsset timezone [zone]` | Zeitzone anzeigen bzw. setzen (IANA, z. B. `Europe/Berlin`, `Europe/Vienna`, `UTC`; Standard `Europe/Berlin`); ungültige Namen werden abgelehnt | Server verwalten |
| `[p]statsset language <de\|en>` | Sprache der Antworten | Server verwalten |
| `[p]statsset settings` | Einstellungen anzeigen | Server verwalten |

Alle Befehle gibt es auch als Slash-Befehl.

## Dashboard
Seite **Statistik** (Icon Diagramm) im WebCore-Dashboard, Server über den Wechsler in der Kopfzeile:

- **Zeitraum** 7 / 30 / 90 Tage (Knöpfe oben rechts).
- **Kennzahlen:** Mitglieder, Netto-Wachstum (rein/raus), Nachrichten (Ø pro Tag), Voice-Stunden.
  Sind **Tickets** bzw. **Raidplaner** geladen, zusätzlich *Offene Tickets* und *Kommende Raids* (nur lesend).
- **Reiter Übersicht:** Diagramme als Inline-SVG (ohne externe Bibliotheken, passend zum Dark-Theme, skalieren
  auf dem Handy mit, Tooltips beim Überfahren/langen Tippen):
  Mitglieder (Linie), Beitritte & Abgänge (Balken nach oben/unten), Nachrichten pro Tag, Voice-Stunden pro Tag,
  Top-10-Text- und Sprachkanäle. **Export** als CSV je Tag oder je Kanal (UTF-8, für Excel).
- **Reiter Kanäle:** alle Kanäle mit Nachrichten und Voice-Stunden im Zeitraum, mit Suche.
- **Reiter Einstellungen:** Aufbewahrung, **Zeitzone** (Freitext mit Vorschlagsliste gängiger Zonen, zeigt die
  aktuelle Uhrzeit dort), Sprache, ignorierte Kanäle; **Statistik zurücksetzen** (mit Bestätigung).

Rechte: **Ansehen** zeigt alles inkl. CSV-Export, **Bearbeiten** erlaubt Einstellungen und Zurücksetzen.

## Datenschutz
Gespeichert werden nur **Tages-Summen je Kanal** – keine Nachrichteninhalte, keine Nutzer-IDs, keine Namen.
Wer gerade in einem Sprachkanal sitzt (für die Zeitmessung), steht nur im Arbeitsspeicher, bis die Sitzung
endet. `red_delete_data_for_user` hat deshalb nichts zu löschen.
