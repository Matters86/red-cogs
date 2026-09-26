# ⏰ Scheduler (Geplante Nachrichten)

Der Bot postet Nachrichten automatisch nach Zeitplan – **einmalig, täglich, an Wochentagen, monatlich oder im
Intervall**. Text und/oder Embed, optional mit Rollen-Ping (es wird **nur diese Rolle** gepingt). Zeitzone pro
Server mit korrekter **Sommerzeit**. Verwaltung per Befehl oder komplett über das **WebCore-Dashboard** (mit
Vorschau und „Jetzt testen“).

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs scheduler
[p]load scheduler
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet.

**Funktionen**
- Text und/oder Embed (Titel, Text, Farbe, Bild), optional Rollen-Ping
- Einmalig, täglich, wöchentlich (Wochentage), monatlich am Tag X (Monatsende sauber), alle N Min./Std. (ab 10 Min.)
- Zeitzone je Server, Start-/Enddatum, pausieren, „Vorherige Nachricht löschen“
- Nach Bot-Downtime **keine** Nachrichten-Flut: verpasste Termine werden nur nachgeholt, wenn der letzte < 10 Minuten her ist
- Nach 5 Fehlern in Folge automatische Pause mit Hinweis im Dashboard

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]schedule add <#kanal> "<zeitplan>" <text>` | Nachricht planen | Server verwalten |
| `[p]schedule list` | Alle Einträge mit nächster Ausführung | Server verwalten |
| `[p]schedule remove <id>` | Eintrag löschen | Server verwalten |
| `[p]schedule pause <id>` | Pausieren | Server verwalten |
| `[p]schedule resume <id>` | Fortsetzen | Server verwalten |
| `[p]schedule test <id>` | Einmal sofort hier posten (ohne Ping) | Server verwalten |
| `[p]schedule timezone [zone]` | Zeitzone anzeigen/setzen | Server verwalten |
| `[p]schedule language <de\|en>` | Sprache der Antworten | Server verwalten |

**Zeitplan-Beispiele**
```
[p]schedule add #news "täglich 09:00" Guten Morgen zusammen!
[p]schedule add #raid "wöchentlich mi,fr 18:00" Heute Abend Raid – bitte anmelden!
[p]schedule add #team "monatlich 31 12:00" Monatsbericht fällig.
[p]schedule add #allgemein "alle 2h" Denkt ans Trinken 💧
[p]schedule add #events "einmalig 24.12.2026 18:00" Frohe Weihnachten! 🎄
```

Im Dashboard (Seite „Geplante Nachrichten“ unter `/cogs/scheduler`): Liste mit nächster Ausführung, Anlegen und
Bearbeiten mit Vorschau, „Jetzt testen“, Pausieren, Löschen, Zeitzone.
