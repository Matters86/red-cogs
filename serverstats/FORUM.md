# 📊 ServerStats – Server-Statistik ohne Personendaten

Wie aktiv ist der Server wirklich? **ServerStats** zählt pro Tag **Beitritte**, **Abgänge**, die
**Mitgliederzahl**, **Nachrichten je Kanal** und **Voice-Zeit je Kanal** – und zeigt alles im Dashboard als
Diagramme für 7, 30 oder 90 Tage.

**Highlights**
- 📈 Kennzahlen + Diagramme: Mitglieder, Beitritte/Abgänge, Nachrichten und Voice-Stunden pro Tag, Top-10-Kanäle
- 🔒 **Keine Personendaten:** nur Tages-Summen je Kanal, keine Inhalte, keine Nutzer-IDs
- 🤖 Bots, Webhooks und der AFK-Kanal zählen nicht; Kanäle lassen sich ausschließen
- 🧾 CSV-Export je Tag oder je Kanal
- 🎫 Zusatz-Kacheln „Offene Tickets“ und „Kommende Raids“, wenn Tickets/Raidplaner geladen sind
- 🕓 Tage in der **Zeitzone des Servers** (Standard Europe/Berlin, Sommerzeit inklusive)
- 🧹 Alte Tage werden automatisch gelöscht (Standard 90 Tage)

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs serverstats
[p]load serverstats
```

**Befehle**
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]stats [tage]` | Kurzübersicht als Embed (Standard 7 Tage, max. 90) | alle |
| `[p]statsset retention <tage>` | Aufbewahrung in Tagen (7–730, Standard 90) | Server verwalten |
| `[p]statsset ignore <#kanal>` | Kanal nicht mehr zählen / wieder zählen | Server verwalten |
| `[p]statsset timezone [zone]` | Zeitzone anzeigen/setzen (IANA, Standard Europe/Berlin) | Server verwalten |
| `[p]statsset language <de\|en>` | Sprache der Antworten | Server verwalten |
| `[p]statsset settings` | Einstellungen anzeigen | Server verwalten |

**Dashboard:** Seite **Statistik** – Zeitraum 7/30/90 Tage, Reiter *Übersicht* (Diagramme, Export),
*Kanäle* (Tabelle mit Suche) und *Einstellungen* (Aufbewahrung, Zeitzone, Sprache, ignorierte Kanäle, Zurücksetzen).

*Update-Hinweis:* Früher wurde in UTC-Tagen gezählt – vorhandene Daten laufen einfach weiter (Versatz max. 2 Stunden).
