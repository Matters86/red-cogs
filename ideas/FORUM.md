# 💡 Ideas (Ideen-Sammler)

Ein **eigenes Ideen-Forum** für eure Community: Mitglieder reichen Ideen per **Formular** ein, jede Idee wird ein
eigener Beitrag `#12 · Titel` mit **Status-Tag**. Das Team setzt den Status mit Begründung, führt Duplikate zusammen
und startet aus mehreren Ideen eine **Umfrage**. Alles auch im **WebCore-Dashboard** und für Mitglieder unter
**Mein Bereich → Ideen**. **Deutsch ist Standard**, Englisch umschaltbar.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs ideas
[p]load ideas
[p]ideaset createforum ideen
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet; für Umfragen zusätzlich `poll`.

**Funktionen**
- Status als Forum-Tags: Neu · In Prüfung · Geplant · Umgesetzt · Abgelehnt · Zusammengeführt (+ Kategorie-Tags)
- Angepinntes Panel „💡 Idee einreichen“ mit Button (übersteht Neustarts) → Kategorie wählen → Formular
- Schutz: Wartezeit (10 Min.), max. 5 offene Ideen je Person, Sperrliste, Hinweis bei ähnlichen Ideen
- Status mit Begründung als Antwort im Beitrag, DM an den Einreicher, bei Umgesetzt/Abgelehnt schließen
- Duplikate zusammenführen, Ideen bearbeiten oder löschen, CSV-Export
- Umfrage aus mehreren Ideen über den Umfragen-Cog – mit Link in jedem Ideen-Beitrag
- Optional anonym, manuell erstellte Beiträge werden übernommen
- Bewusst ohne 👍/👎 – abgestimmt wird gezielt per Umfrage

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]ideas status <nr> <status> [kommentar]` | Status setzen (neu, prüfung, geplant, umgesetzt, abgelehnt) | Team |
| `[p]ideas comment <nr> <text>` | Kommentar im Beitrag posten | Team |
| `[p]ideas merge <duplikat> <ziel>` | Duplikat zusammenführen | Team |
| `[p]ideas edit <nr> <titel\|beschreibung\|kategorie> <wert>` | Idee bearbeiten | Team |
| `[p]ideas delete <nr> ja` | Idee + Beitrag löschen | Team |
| `[p]ideas block/unblock <@mitglied>` | Mitglied sperren/entsperren | Team |
| `[p]ideas list [status\|offen]` | Ideen auflisten | Team |
| `[p]ideas export` | CSV-Export | Team |
| `[p]ideas poll <nr> <nr> … [\| frage]` | Umfrage aus Ideen | Team |
| `[p]ideaset forum <#forum>` | Ideen-Forum festlegen | Server verwalten |
| `[p]ideaset createforum [name]` | Forum mit Tags, Rechten und Panel anlegen | Server verwalten |
| `[p]ideaset panel` | Panel posten/erneuern | Server verwalten |
| `[p]ideaset categories <a \| b \| c>` | Kategorien festlegen | Server verwalten |
| `[p]ideaset teamrole <rolle>` | Team-Rolle umschalten | Server verwalten |
| `[p]ideaset anonymous\|dm\|archive\|manual <true\|false>` | Schalter | Server verwalten |
| `[p]ideaset cooldown <min>` / `maxopen <n>` | Wartezeit / Limit | Server verwalten |
| `[p]ideaset language <de\|en>` · `settings` | Sprache · Übersicht | Server verwalten |

**Team** = Bot-Owner, „Server verwalten“ oder Ideen-Team-Rolle.

**Dashboard:** Seite **Ideen** – Kennzahlen, Ideen-Tabelle mit Filtern und Auswahl, Details mit Verlauf, Umfrage aus
Ideen, Einstellungen (Forum anlegen, Panel, Tags), Sperren, CSV-Export. Stufe **Bedienen** reicht für Status,
Kommentar, Zusammenführen, Bearbeiten, Löschen und Umfragen; Einstellungen und Sperren brauchen **Bearbeiten**.
