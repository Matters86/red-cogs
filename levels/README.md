# Levels

**Levelsystem** für Red: Mitglieder sammeln **XP** für Nachrichten (und optional für Zeit in Sprachkanälen),
steigen im **Level** auf, bekommen **Rollen-Belohnungen** und eine **Rangkarte** als Bild. Mit Rangliste,
Level-Up-Meldungen, ausgeschlossenen Kanälen/Rollen und XP-Multiplikatoren. Team-Dashboard **Level** und
Mitglieder-Seite **Mein Level** im WebCore.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs levels
[p]load levels
```
Abhängigkeit: `Pillow` (wird mitinstalliert). Bot-Rechte: **Rollen verwalten** (Belohnungen; die Bot-Rolle muss
**über** den Belohnungsrollen liegen), im Meldungs-Kanal **Nachrichten senden**, für `[p]rank` **Dateien anhängen**
(sonst kommt ein Embed). Members-Intent empfohlen (Rangliste zeigt nur Mitglieder, die noch auf dem Server sind).

## So funktioniert's
- **Nachrichten:** zufällig **15–25 XP** pro Nachricht, höchstens eine Nachricht pro **60 s** und Mitglied zählt
  (beides einstellbar). Bots, Webhooks und DMs zählen nicht.
- **Voice (optional, Standard aus):** jede Minute **5 XP** für alle, die **nicht allein** im Kanal sind (mind. ein
  weiterer Mensch), **nicht stumm/taub** (selbst oder vom Server) und **nicht im AFK-Kanal** sitzen.
- **Ausschlüsse:** Kanäle ohne XP (gilt auch für Threads darin und für Voice) und Rollen ohne XP.
- **Multiplikatoren:** Rollen mit Faktor 0,1–5 (z. B. Booster ×1,5). Hat jemand mehrere, gilt der **höchste**.

### Levelkurve (wie MEE6)
Von Level **L** nach **L+1** braucht man

```
XP(L) = 5·L² + 50·L + 100
```

| Level | XP für diesen Schritt | Gesamt-XP ab diesem Level |
|---|---|---|
| 1 | 100 | 100 |
| 2 | 155 | 255 |
| 3 | 220 | 475 |
| 5 | 380 (von 4 → 5) | 1.150 |
| 10 | 955 (von 9 → 10) | 4.675 |

### Level-Up-Meldung
`off` (aus) · `same` (im Kanal der Nachricht; bei Voice-Level-Ups keine Meldung) · `channel` (fester Kanal) ·
`dm`. Eigener Text mit Platzhaltern `{user}` (Erwähnung), `{name}`, `{level}`, `{server}` – unbekannte `{…}`
bleiben stehen. Gepingt wird **höchstens das Mitglied selbst**, nie `@everyone`/`@here`/Rollen.

### Rollen-Belohnungen
Pro Level eine Rolle. **Stapeln** (Standard): alle erreichten Rollen behalten – oder **nur die höchste**
(niedrigere werden entfernt). Sinkt das Level (XP abgezogen/zurückgesetzt), werden zu hohe Belohnungen entfernt.
Abgeglichen wird bei jedem Level-Wechsel; nach dem Anlegen neuer Belohnungen `[p]levelset syncrewards` bzw.
„Jetzt für alle abgleichen“ im Dashboard. Schutz: Rollen über der Bot-Rolle, `@everyone` und Integrations-Rollen
werden abgelehnt; per Befehl kann man nur Rollen **unter der eigenen höchsten Rolle ohne Moderationsrechte**
eintragen (Server-Inhaber/Bot-Owner: alle), im Dashboard gilt `webcore.can_grant_role` (Schutz vor Selbst-Hochstufung).

## Befehle
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]rank [@mitglied]` | Rangkarte (Bild) mit Rang, Level und Fortschritt | alle |
| `[p]leaderboard [seite]` / `[p]top` | Rangliste, 10 pro Seite | alle |
| `[p]levelset xp <give\|take\|set\|reset> <@mitglied> [menge]` | XP geben/abziehen/setzen/zurücksetzen (ohne Level-Up-Meldung) | Server verwalten |
| `[p]levelset toggle [on\|off]` | Levelsystem an/aus | Server verwalten |
| `[p]levelset xprange <min> <max>` | XP pro Nachricht (Standard 15–25) | Server verwalten |
| `[p]levelset cooldown <sekunden>` | Cooldown pro Mitglied (Standard 60) | Server verwalten |
| `[p]levelset voice <on\|off> [xp_pro_minute]` | Voice-XP | Server verwalten |
| `[p]levelset excludechannel <#kanal>` | Kanal ohne XP (erneut = wieder mit XP) | Server verwalten |
| `[p]levelset excluderole <@rolle>` | Rolle ohne XP (erneut = wieder mit XP) | Server verwalten |
| `[p]levelset multiplier <@rolle> <faktor>` | XP-Multiplikator (0,1–5; 1 = entfernen) | Server verwalten |
| `[p]levelset reward <level> [@rolle]` | Belohnung setzen (ohne Rolle = entfernen) | Server verwalten |
| `[p]levelset stack <on\|off>` | Belohnungen stapeln oder nur die höchste | Server verwalten |
| `[p]levelset syncrewards` | Belohnungsrollen aller Mitglieder abgleichen | Server verwalten |
| `[p]levelset announce <off\|same\|channel\|dm> [#kanal]` | Level-Up-Meldung | Server verwalten |
| `[p]levelset message [text]` | Text der Meldung (ohne Text = Standard) | Server verwalten |
| `[p]levelset language <de\|en>` | Sprache (Meldungen, Antworten, Rangkarte) | Server verwalten |
| `[p]levelset settings` | Einstellungen anzeigen | Server verwalten |

Alle Befehle gibt es auch als Slash-Befehl (`/top` nur als Textbefehl-Alias von `leaderboard`).

## Dashboard
Seite **Level** (Icon Pokal) im WebCore-Dashboard:

- **Rangliste** mit Suche, Level, XP und Fortschrittsbalken (Top 500).
- **Belohnungen:** Liste mit Status (z. B. „über Bot-Rolle“), hinzufügen/entfernen, Modus stapeln/nur höchste,
  „Jetzt für alle abgleichen“.
- **Einstellungen:** an/aus, Sprache, Kartenfarbe, Schalter **„Im Mitglieder-Bereich anzeigen“**, XP pro
  Nachricht, Cooldown, Voice-XP, ausgeschlossene Kanäle/Rollen, Level-Up-Meldung; XP-Multiplikatoren.
- **XP anpassen:** Mitglied (ID, Erwähnung oder eindeutiger Name), geben/abziehen/setzen/zurücksetzen – mit Bestätigung.

Rechte: **Ansehen** = alles schreibgeschützt, **Bearbeiten** = alle Einstellungen dieses Servers.

### Mein Bereich → „Mein Level“
Mitglieder sehen unter `/me/level` ihren **Rang**, **Level**, einen **Fortschrittsbalken**, ihre **Rangkarte**
als Bild, die **nächste Belohnung** und die **Top 10** des Servers (nur Anzeigenamen). Abschaltbar über den
Schalter im Team-Dashboard; den Mitglieder-Bereich selbst schaltet der Bot-Owner unter *Zugriff & Rollen* ein.

## Datenschutz & Technik
Gespeichert wird pro Server und Mitglied: **XP**, **Level**, **Zeitpunkt der letzten XP-Nachricht** (Cooldown).
Keine Nachrichteninhalte. `red_delete_data_for_user` löscht diese Daten auf allen Servern.
Alle Mitgliedsdaten eines Servers werden einmal geladen und im Arbeitsspeicher gehalten; Änderungen werden
**alle 60 s** (und beim Entladen) gebündelt gespeichert. Die Rangkarte wird im Hintergrund-Thread gerendert,
Avatare mit Timeout (8 s) und Größenlimit (4 MB) geladen. Schriften (Archivo, IBM Plex Sans, SIL OFL 1.1)
liegen in `assets/fonts`.
