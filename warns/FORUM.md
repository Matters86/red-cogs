# Warns

**Verwarnsystem** mit **Punkten**, **Verfall** und **automatischen Maßnahmen** (Timeout, Kick, Bann ab X
aktiven Punkten) – mit Hierarchie-Schutz (nie gegen Owner oder höhere Rollen), DM an Verwarnte, Log-Kanal
und einer Dashboard-Seite mit durchsuchbarem Verlauf. Deutsch/Englisch.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs warns
[p]unload warnings
[p]load warns
```
(`[p]unload warnings` entlädt Reds eingebauten Warnings-Cog – gleiche Befehlsnamen.)

## Schnellstart
```
[p]warnset logchannel #mod-log
[p]warnset modrole @Moderator
[p]warnset action timeout 3 60
[p]warn @Nutzer Spam im Chat
```

## Befehle
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]warn @user [punkte] <grund>` | Mitglied verwarnen | Moderator |
| `[p]warnings [@user]` | Verwarnungen anzeigen | jeder (eigene) / Moderator |
| `[p]unwarn <id>` | Verwarnung aufheben | Moderator |
| `[p]clearwarns @user` | Alle Verwarnungen löschen | Administrator |
| `[p]warnset logchannel [#kanal]` | Log-Kanal | Server verwalten |
| `[p]warnset dm <on\|off>` | DM an Verwarnte | Server verwalten |
| `[p]warnset dmtext [text]` | DM-Text | Server verwalten |
| `[p]warnset modrole <rolle>` | Mod-Rolle an/aus | Server verwalten |
| `[p]warnset expiry <tage>` | Verfall (0 = nie) | Server verwalten |
| `[p]warnset points <n>` | Standard-Punkte | Server verwalten |
| `[p]warnset action <timeout\|kick\|ban> <punkte> [minuten]` | Automatische Maßnahme (0 = aus) | Server verwalten |
| `[p]warnset language <de\|en>` | Sprache | Server verwalten |
| `[p]warnset settings` | Einstellungen anzeigen | Server verwalten |

Moderator = Mitglieder kicken, Mod-Rolle, Admin, Server-Owner oder Bot-Owner.

## Dashboard
Seite **Verwarnungen**: Kennzahlen, **Verlauf** (Suche, Filter aktiv/alle, Aufheben), **Mitglied verwarnen**
(du bist der Moderator, gleiche Prüfungen wie der Befehl), **Automatische Maßnahmen** und **Einstellungen**.
