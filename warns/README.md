# Warns

**Verwarnsystem** für Moderatoren: Verwarnungen mit Grund und **Punkten**, optionalem **Verfall**
und **automatischen Maßnahmen** (Timeout, Kick, Bann) ab einer einstellbaren Punktzahl.

Highlights:

- `[p]warn`, `[p]warnings`, `[p]unwarn`, `[p]clearwarns` als Text- und Slash-Befehle.
- **Punkte je Verwarnung** (Standard 1, Standard pro Server einstellbar) und **Verfall** nach N Tagen
  (0 = nie; gilt für neu erstellte Verwarnungen).
- **Automatische Maßnahmen** (Standard aus): Timeout (mit Dauer), Kick oder Bann, sobald eine neue
  Verwarnung die Schwelle **erreicht**; bei mehreren erreichten Schwellen die schwerste.
- **Hierarchie-Schutz:** keine Verwarnung/Maßnahme gegen Bot-Owner, Server-Owner, Bots, sich selbst
  oder Mitglieder mit gleich hoher/höherer Rolle als der Moderator; Maßnahmen außerdem nie gegen
  Mitglieder mit gleich hoher/höherer Rolle als der Bot, kein Timeout für Administratoren.
  Grund und Ergebnis stehen im Log.
- **DM an Verwarnte** (Schalter, eigener Text mit Platzhaltern) – bei Kick/Bann vor der Maßnahme.
- **Log-Kanal** mit Embed für Verwarnen, Aufheben und Löschen.
- IDs **fortlaufend je Server**, atomar vergeben (kein doppelter Eintrag bei gleichzeitigen Verwarnungen).
- **Dashboard-Seite „Verwarnungen“** mit durchsuchbarem Verlauf und Verwarnen per Formular.

> **Hinweis:** Red bringt einen eigenen Cog **warnings** mit denselben Befehlsnamen. Vorher entladen:
> `[p]unload warnings`. Der Ordner heißt deshalb `warns` (ein Paket namens `warnings` würde außerdem
> Pythons Standardmodul im Bot-Prozess überdecken).

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs warns
[p]load warns
```

Bot-Rechte für automatische Maßnahmen: **Mitglieder im Timeout**, **Mitglieder kicken**,
**Mitglieder bannen** – und die Bot-Rolle muss über den betroffenen Mitgliedern stehen.

## Schnellstart

```
[p]warnset logchannel #mod-log
[p]warnset modrole @Moderator
[p]warnset action timeout 3 60
[p]warnset action kick 5
[p]warn @Nutzer Spam im Chat
[p]warn @Nutzer 2 Beleidigung
```

## Befehle

„Moderator“ = Bot-Owner, Server-Owner, Administrator, **Mitglieder kicken**, eine eingestellte
Mod-Rolle oder Reds Mod-Rolle.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]warn @user [punkte] <grund>` | Verwarnt ein Mitglied; eine führende Zahl im Grund sind die Punkte (1–100) | Moderator |
| `[p]warnings [@user]` | Verwarnungen anzeigen (ohne Angabe: die eigenen) | jeder (eigene) / Moderator (andere) |
| `[p]unwarn <id>` | Verwarnung aufheben (bleibt im Verlauf, zählt nicht mehr) | Moderator |
| `[p]clearwarns @user` | Alle Verwarnungen eines Mitglieds endgültig löschen | Administrator |
| `[p]warnset logchannel [#kanal]` | Log-Kanal (ohne Kanal = aus) | Server verwalten |
| `[p]warnset dm <on\|off>` | DM an Verwarnte | Server verwalten |
| `[p]warnset dmtext [text]` | DM-Text (leer = Standard) | Server verwalten |
| `[p]warnset modrole <rolle>` | Mod-Rolle hinzufügen/entfernen (Umschalter) | Server verwalten |
| `[p]warnset expiry <tage>` | Verfall neuer Verwarnungen (0 = nie) | Server verwalten |
| `[p]warnset points <n>` | Standard-Punkte je Verwarnung | Server verwalten |
| `[p]warnset action <timeout\|kick\|ban> <punkte> [minuten]` | Automatische Maßnahme ab X aktiven Punkten (0 = aus); Timeout-Dauer in Minuten | Server verwalten |
| `[p]warnset language <de\|en>` | Sprache | Server verwalten |
| `[p]warnset settings` | Einstellungen anzeigen | Server verwalten |

Regeln beim Verwarnen (Befehl und Dashboard): nicht sich selbst, keine Bots, nicht den Bot-Owner oder
Server-Owner und nur Mitglieder **unter** der eigenen höchsten Rolle (Bot-/Server-Owner dürfen alle).
Eigene Verwarnungen kann man nicht aufheben (außer Bot-/Server-Owner).

## DM-Platzhalter

`{user}` Erwähnung · `{name}` Name · `{server}` Server · `{reason}` Grund · `{points}` Punkte ·
`{total}` aktive Punkte · `{id}` Verwarnungs-ID · `{moderator}` Moderator · `{expires}` Ablauf

## Dashboard

Seite **Verwarnungen** (Icon Achteck) im WebCore-Dashboard:

- **Kennzahlen:** aktive Verwarnungen, betroffene Mitglieder, Verwarnungen der letzten 7 Tage, aktive Maßnahmen.
- **Verlauf:** durchsuchbare Tabelle (Filter „Nur aktive“ / „Alle“) mit Status, Ablauf und ausgeführter
  Maßnahme; **Aufheben** mit Bestätigung.
- **Mitglied verwarnen:** Mitglied per Name/ID (mit Vorschlägen), Grund, Punkte. Moderator ist der
  angemeldete Dashboard-User; es gelten dieselben Prüfungen wie beim Befehl (Hierarchie gegenüber dir).
- **Automatische Maßnahmen:** Schwellen für Timeout (mit Dauer), Kick und Bann; Warnung, wenn dem Bot Rechte fehlen.
- **Einstellungen:** Log-Kanal, Mod-Rollen, Verfall, Standard-Punkte, Sprache, DM an/aus und DM-Text.

Rechte: **Ansehen** zeigt Verlauf und Einstellungen schreibgeschützt; **Bearbeiten** erlaubt Verwarnen,
Aufheben und Speichern – nur für den jeweiligen Server.

## Datenschutz

Gespeichert werden pro Server die Verwarnungen (Nutzer-ID, Anzeigename, Grund, Punkte, Zeitpunkt,
Moderator-ID und -Name). Bei einer Löschanfrage (`[p]mydata forgetme` bzw. durch den Owner) werden die
Verwarnungen des Nutzers gelöscht und er wird als Moderator anonymisiert.
