# 🏆 Levels – XP, Ränge, Belohnungen & Rangkarte

Mitglieder sammeln **XP** fürs Schreiben (und optional für Zeit in Sprachkanälen), steigen im **Level** auf und
bekommen automatisch **Rollen-Belohnungen**. Mit schicker **Rangkarte**, **Rangliste** und Level-Up-Meldungen.

**Highlights**
- ✍️ 15–25 XP pro Nachricht, 60 s Cooldown (einstellbar), Bots/Webhooks zählen nicht
- 🎙️ Optional Voice-XP pro Minute – nicht allein, nicht stumm/taub, nicht im AFK-Kanal
- 📈 Levelkurve wie MEE6: `5·L² + 50·L + 100` XP pro Level
- 🎁 Rollen-Belohnungen je Level (stapeln oder nur die höchste) mit Hierarchie-Schutz
- 🖼️ Rangkarte als Bild (`[p]rank`), Rangliste (`[p]leaderboard` / `[p]top`)
- 📣 Level-Up-Meldung im selben Kanal, festen Kanal oder per DM – ohne Massen-Pings
- 🚫 Ausgeschlossene Kanäle/Rollen, ⚡ XP-Multiplikatoren für Rollen
- 🌐 Dashboard **Level** + Mitglieder-Seite **Mein Level** (Rang, Fortschritt, Karte, Top 10)

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs levels
[p]load levels
```

**Befehle**
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]rank [@mitglied]` | Rangkarte mit Rang, Level und Fortschritt | alle |
| `[p]leaderboard [seite]` / `[p]top` | Rangliste, 10 pro Seite | alle |
| `[p]levelset xp <give\|take\|set\|reset> <@mitglied> [menge]` | XP anpassen | Server verwalten |
| `[p]levelset toggle [on\|off]` | Levelsystem an/aus | Server verwalten |
| `[p]levelset xprange <min> <max>` | XP pro Nachricht | Server verwalten |
| `[p]levelset cooldown <sekunden>` | Cooldown pro Mitglied | Server verwalten |
| `[p]levelset voice <on\|off> [xp_pro_minute]` | Voice-XP | Server verwalten |
| `[p]levelset excludechannel <#kanal>` | Kanal ohne XP (umschalten) | Server verwalten |
| `[p]levelset excluderole <@rolle>` | Rolle ohne XP (umschalten) | Server verwalten |
| `[p]levelset multiplier <@rolle> <faktor>` | XP-Multiplikator (1 = entfernen) | Server verwalten |
| `[p]levelset reward <level> [@rolle]` | Belohnung setzen/entfernen | Server verwalten |
| `[p]levelset stack <on\|off>` | Belohnungen stapeln / nur höchste | Server verwalten |
| `[p]levelset syncrewards` | Belohnungsrollen aller Mitglieder abgleichen | Server verwalten |
| `[p]levelset announce <off\|same\|channel\|dm> [#kanal]` | Level-Up-Meldung | Server verwalten |
| `[p]levelset message [text]` | Meldungstext (`{user}` `{name}` `{level}` `{server}`) | Server verwalten |
| `[p]levelset language <de\|en>` | Sprache | Server verwalten |
| `[p]levelset settings` | Einstellungen anzeigen | Server verwalten |

**Dashboard:** Seite **Level** mit den Reitern *Rangliste*, *Belohnungen*, *Einstellungen* und *XP anpassen*.
Mitglieder finden unter **Mein Bereich → Mein Level** ihren Rang, ihre Rangkarte und die Top 10.
