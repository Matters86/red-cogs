# 🎉 Giveaways (Gewinnspiele)

Gewinnspiele für Red – per Befehl **oder** komplett über das **WebCore-Dashboard**. Teilnahme per **🎉-Button**
(übersteht Neustarts), automatische und **faire Auslosung** (kryptografisch sicherer Zufall) – auch wenn der Bot
beim Ende offline war. Die Ansage pingt **nur die Gewinner**. **Deutsch ist Standard**, Englisch umschaltbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs giveaways
[p]load giveaways
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet.

**Funktionen**
- Preis, Beschreibung, Kanal, 1–20 Gewinner, Ende per Dauer (`2d`, `12h`) oder Datum/Uhrzeit
- Benötigte Rollen, ausgeschlossene Rollen, Mindest-Mitgliedschaft in Tagen
- Bonus-Lose für Rollen (z. B. Booster +2)
- Erneuter Klick = austreten (mit Rückfrage, nur für dich sichtbar)
- Teilnehmerzahl im Embed, gedrosselt aktualisiert
- Vorzeitig beenden, abbrechen, einzelne oder alle Gewinner neu auslosen
- Mitglieder nehmen auch unter **Mein Bereich → Gewinnspiele** teil und sehen ihre Gewinne

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]giveaway start <dauer> <gewinner> <preis>` | Gewinnspiel in diesem Kanal starten | Manager |
| `[p]giveaway end <id>` | Vorzeitig beenden und auslosen | Manager |
| `[p]giveaway reroll <id> [@nutzer]` | Alle Gewinner oder nur `@nutzer` neu auslosen | Manager |
| `[p]giveaway cancel <id>` | Abbrechen (ohne Auslosung) | Manager |
| `[p]giveaway list` | Alle Gewinnspiele des Servers | Manager |
| `[p]giveaway managerrole <rolle>` | Manager-Rolle hinzufügen/entfernen | Server verwalten |
| `[p]giveaway language <de\|en>` | Sprache setzen | Server verwalten |

Manager = „Server verwalten“ oder eine Manager-Rolle (Bot-Owner immer).

**Beispiel**
```
[p]giveaway start 1d 2 Discord Nitro (1 Monat)
[p]giveaway reroll 3 @Nutzer
```

Im Dashboard (Seite „Gewinnspiele“ unter `/cogs/giveaways`): laufende und beendete Gewinnspiele mit Suche,
Detailansicht mit Teilnehmerliste, „Neues Gewinnspiel“ mit Rollen-Regeln und Bonus-Losen, Einstellungen.
