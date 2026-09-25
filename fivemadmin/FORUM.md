# 🚓 FiveM-Adminpanel

Verwalte deinen **FiveM-Server (QBox)** direkt aus Discord **oder** über ein eigenes Webpanel –
beide nutzen dieselbe Action-Queue, der Server holt die Aufträge über die Resource `ap_bridge` ab.
Rechte kommen **live aus den Discord-Rollen**: Rolle weg = Zugriff sofort weg.

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs fivemadmin
[p]load fivemadmin
```

**Einrichtung in 3 Schritten**
1. `[p]ap config key` → Key kommt per DM → in `server.cfg` eintragen, `ap_bridge` neu starten
2. `[p]ap config url https://panel.deinedomain.tld`
3. `[p]ap roles set support @Support` (weitere Presets: `moderator`, `admin`, `editor`)

Kontrolle: `[p]ap diag` und `[p]ap config show`.

**Funktionen**
- Support: Teleport, Heilen, Wiederbeleben, Fahrzeuge einparken, Nachrichten, Ansagen
- Moderation: Kick, Ban/Unban, Notizen & Verwarnungen in der Spielerakte, Spielersuche
- Admin: Geld/Items mit Limits, Job/Gang, Statistiken, Audit-Log
- Webpanel als App installierbar, Login per Einmal-Link oder „Mit Discord anmelden"
- Not-Aus `[p]ap lockdown on`, Audit- und Alert-Kanal, tägliches DB-Backup

**Wichtigste Befehle**

| Befehl | Beschreibung |
|---|---|
| `[p]ap login` | Login-Link fürs Webpanel per DM |
| `[p]ap tp <spieler> <ziel>` | Spieler zu Spieler teleportieren |
| `[p]ap heal` / `revive <spieler>` | Heilen / Wiederbeleben |
| `[p]ap find <name\|cid>` | Spieler suchen (auch offline) |
| `[p]ap kick` / `ban` / `unban` | Moderation |
| `[p]ap money <spieler> <add\|remove> <betrag> [cash\|bank]` | Geld (Admin) |
| `[p]ap lockdown [on\|off]` | Not-Aus für alle Panel-Aktionen |

Alle Befehle: `[p]help ap`.

**Hinweis:** Das Panel läuft auf einem eigenen Port (Standard `8099`) – nach außen bitte nur
über einen HTTPS-Reverse-Proxy freigeben.
