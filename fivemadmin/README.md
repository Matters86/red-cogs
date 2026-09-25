# FiveM-Adminpanel (`fivemadmin`)

Verwaltung eines **FiveM-Servers (QBox)** per Discord-Befehl **und** eigenem Webpanel. Beide
Wege schreiben in dieselbe **Action-Queue**; der FiveM-Server holt die Aufträge über die
Bridge-Resource `ap_bridge` per HTTP ab und meldet das Ergebnis zurück.

- **Support-Aktionen:** Teleport (zu Spieler/Koordinaten), Heilen, Wiederbeleben, Fahrzeuge
  einparken (einzeln oder alle), private Nachrichten, Ansagen.
- **Moderation:** Kick, Ban (Stunden oder permanent), Unban, Team-Notizen und Verwarnungen in
  der Spielerakte, Spielersuche (auch offline).
- **Admin:** Geld und Items geben/nehmen (mit Limits pro Aktion), Job/Gang setzen, Statistiken,
  Audit-Log.
- **Webpanel** (installierbar als App/PWA) mit Tabs Spieler, Statistiken, Server, Audit und
  Protokoll; Login per Einmal-Link (`[p]ap login`) oder „Mit Discord anmelden" (OAuth2).
- **Rechte live aus Discord:** Jede Anfrage prüft die aktuellen Rollen – Rolle entzogen =
  sofort kein Zugriff mehr.
- **Sicherheit:** Not-Aus (`lockdown`), Audit-Channel für heikle Aktionen, Missbrauchs-Alerts,
  tägliches automatisches DB-Backup (auch nach Neustarts: fällig, sobald das letzte älter als 24 h ist).

> Dieser Cog bringt für die Aktionen im Spiel ein **eigenes Live-Panel** mit eigenem Webserver mit
> (nicht WebCore). Die **Verwaltung** (Not-Aus, Sperren, Panel-Rechte, Einstellungen, Anmelden im
> Live-Panel) gibt es zusätzlich als Seite **„FiveM-Admin“ im WebCore-Dashboard** – siehe unten.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs fivemadmin
[p]load fivemadmin
```

## Einrichtung

1. **API-Key erzeugen:** `[p]ap config key` – der Key kommt per DM. In der `server.cfg` des
   FiveM-Servers eintragen (`set adminpanel_key "<key>"`) und `ap_bridge` neu starten.
   Solange kein eigener Key gesetzt ist, sind alle Bridge-Endpunkte gesperrt (HTTP 503).
2. **Panel-URL setzen:** `[p]ap config url https://panel.deinedomain.tld` – damit kommen die
   Login-Links anklickbar per DM.
3. **Rollen zuordnen:** `[p]ap roles set <preset> @Rolle` (siehe Presets unten).
4. Optional: `[p]ap config oauth <client_id> <client_secret>` für „Mit Discord anmelden"
   (Nachricht mit dem Secret wird sofort gelöscht), `[p]ap auditchannel #kanal`,
   `[p]ap logchannel #kanal`.
5. Prüfen: `[p]ap diag` (DB, Exports, Tabellen, Society-System) und `[p]ap config show`.

**Reverse-Proxy empfohlen:** Das Panel lauscht auf Port `8099` (änderbar mit
`[p]ap config port`, aktiv nach `[p]reload fivemadmin`) und standardmäßig auf allen
Netzwerk-Schnittstellen. Läuft der Proxy auf demselben Rechner, `[p]ap config bind 127.0.0.1`
setzen – dann ist das Panel nur noch über den Proxy erreichbar. Nach außen nur über HTTPS
(z. B. nginx/Caddy/Synology-Reverse-Proxy) freigeben – Session-Token und API-Key sollten nie
unverschlüsselt übers Netz gehen.

### Presets

| Preset | Rechte |
|---|---|
| `support` | Spielerliste, Teleport, Heilen, Wiederbeleben, Fahrzeug einparken, Inventar ansehen, Nachrichten |
| `moderator` | support + Kick, Ban, Ansage, Protokoll, Notizen, Job/Gang setzen |
| `admin` | moderator + Geld, Items, Statistiken, alle Fahrzeuge einparken, Audit |
| `editor` | Server-Status-Dashboard + Statistiken (additiv kombinierbar) |

Discord-Administratoren haben automatisch alle Rechte. Einzelne Personen können im Webpanel
zusätzlich ein Preset erhalten.

## Befehle

| Befehl | Beschreibung | Recht |
|---|---|---|
| `[p]ap login` | Einmal-Link/Token fürs Webpanel per DM (5 Min gültig). | beliebiges Preset |
| `[p]ap tp <spieler> <ziel>` | Spieler zu Spieler teleportieren. | teleport |
| `[p]ap tpc <spieler> <x> <y> <z>` | Spieler zu Koordinaten teleportieren. | teleport |
| `[p]ap heal <spieler>` | Spieler vollständig heilen. | heal |
| `[p]ap revive <spieler>` | Spieler wiederbeleben. | revive |
| `[p]ap car2garage <kennzeichen> [garage]` | Fahrzeug in eine Garage einparken. | car_to_garage |
| `[p]ap cars <spieler>` | Fahrzeuge eines Spielers (auch offline). | car_to_garage |
| `[p]ap parkall [garage]` | Alle gespawnten, unbesetzten Fahrzeuge einparken. | park_all |
| `[p]ap msg <spieler> <text>` | Private Support-Nachricht an einen Spieler. | message |
| `[p]ap announce <text>` | Server-Ansage an alle Spieler. | announce |
| `[p]ap find <name\|cid>` | Spieler in der DB suchen (auch offline). | view_players |
| `[p]ap inv <spieler>` | Inventar anzeigen. | view_inventory |
| `[p]ap kick <spieler> [grund]` | Spieler kicken. | kick |
| `[p]ap ban <spieler> <stunden\|perm> <grund>` | Spieler bannen. | ban |
| `[p]ap unban <citizenid>` | Ban aufheben. | ban |
| `[p]ap bans` | Aktive Bans anzeigen. | ban |
| `[p]ap note <citizenid> <text>` | Team-Notiz zur Spielerakte. | notes |
| `[p]ap warn <citizenid> <text>` | Verwarnung zur Spielerakte. | notes |
| `[p]ap setjob <spieler> <job> [grad]` | Job eines Online-Spielers setzen. | setjob |
| `[p]ap setgang <spieler> <gang> [grad]` | Gang eines Online-Spielers setzen. | setjob |
| `[p]ap money <spieler> <add\|remove> <betrag> [cash\|bank]` | Geld geben/nehmen (Limit: `moneymax`). | money |
| `[p]ap giveitem <spieler> <item> [anzahl]` | Item geben (Limit: `itemmax`). | items |
| `[p]ap removeitem <spieler> <item> [anzahl]` | Item wegnehmen. | items |
| `[p]ap diag` | Setup-Diagnose über die Bridge. | server_status |
| `[p]ap status` | Die letzten 10 Aktionen. | beliebiges Preset |
| `[p]ap roles set\|remove\|list` | Rollen-Presets verwalten. | Discord-Administrator |
| `[p]ap config show\|key\|url\|port\|bind\|moneymax\|itemmax\|oauth` | Panel-Einstellungen (`bind 127.0.0.1` = nur über Reverse-Proxy erreichbar). | Discord-Administrator |
| `[p]ap auditchannel [kanal]` | Kanal für das Audit-Log (ohne Angabe: aus). | Discord-Administrator |
| `[p]ap logchannel [kanal]` | Kanal für Missbrauchs-Alerts (ohne Angabe: aus). | Discord-Administrator |
| `[p]ap backup` | Sofort ein DB-Backup erstellen. | Discord-Administrator |
| `[p]ap lockdown [on\|off]` | **Not-Aus:** sperrt sofort alle Aktionen (Webpanel **und** Discord-Befehle) und verwirft alle noch offenen Aufträge. Lesende Befehle (`find`, `inv`, `cars`, `bans`, `diag`) bleiben nutzbar. | Discord-Administrator |

## Dashboard (WebCore)

Ist [WebCore](../webcore/) geladen, erscheint die Seite **FiveM-Admin** im gemeinsamen Dashboard
(`/cogs/fivemadmin`). Das Live-Panel bleibt unverändert für alle Aktionen im Spiel (Spielerliste,
Teleport, Geld, Items …), inklusive App/PWA und Bridge-Endpunkten.

| Reiter | Inhalt |
|---|---|
| **Übersicht** | Kennzahlen (Bridge-Status und letzter Sync, Spieler online, offene Aufträge, Lockdown, aktive Sperren), **Live-Panel**-Karte mit „Im Live-Panel anmelden“ (Single Sign-on) und „Live-Panel öffnen“, **Not-Aus** (Lockdown an/aus mit Bestätigung), Einrichtungsprüfung (API-Key, Panel-URL, Bridge, Rollen, Kanäle, OAuth) und die letzten 150 Aufträge als durchsuchbare Tabelle. |
| **Sperren** | Aktive Bans mit Suche; Entbannen mit Bestätigung. |
| **Panel-Rechte** | Erklärung der Presets, Zuordnung **Rolle → Preset** und **Einzelpersonen → Preset** (hinzufügen per ID, Erwähnung oder Name). Verwaiste Einträge gelöschter Rollen lassen sich entfernen. |
| **Einstellungen** | Audit- und Alert-Kanal, Geld-/Item-Limit pro Aktion, Panel-URL. API-Key, OAuth-Daten, Port und Bind-Adresse werden nur angezeigt („gesetzt“/„nicht gesetzt“ bzw. Port/Adresse) – ändern nur per Discord-Befehl. |

**Anmelden im Live-Panel (Single Sign-on):** Der Button erzeugt für den im Dashboard angemeldeten
Discord-Nutzer einen Einmal-Login (5 Min. gültig) – genau wie `[p]ap login` – und leitet direkt auf
`<Panel-URL>/?login=…` weiter. Voraussetzungen: Panel-URL gesetzt, Panel-Rechte auf dem gewählten
Server und auf der Dashboard-Seite das Recht *Bearbeiten* (die Anmeldung ist ein Formular-POST mit
CSRF-Schutz). Mit nur *Ansehen* erscheint ein Hinweis auf `[p]ap login`.

**Rechte:** Wer die Seite überhaupt sieht bzw. bearbeiten darf, legt der Bot-Owner unter
*Verwaltung → Zugriff & Rollen* fest (WebCore-Rollen-Rechte, pro Server). **Zusätzlich** prüft jede
Aktion serverseitig dieselben Rechte wie der passende Befehl bzw. Live-Panel-Endpunkt:

| Aktion | Nötig (neben WebCore-„Bearbeiten“) |
|---|---|
| Entbannen | Panel-Recht *Bannen* (Preset `moderator` oder `admin`) – wie `[p]ap unban` |
| Lockdown an/aus | Discord-Administrator des Servers – wie `[p]ap lockdown` |
| Panel-Rechte ändern | Discord-Administrator des Servers – wie `[p]ap roles`; zusätzlich kann niemand ein Preset vergeben oder entziehen, das mehr Rechte hat als er selbst |
| Einstellungen | nur Bot-Owner/Allowlist, weil sie **botweit** gelten |
| Im Live-Panel anmelden | irgendein Panel-Recht auf dem Server – wie `[p]ap login` |

**Sichtbarkeit wie im Live-Panel:** Die Sperrliste sieht nur, wer das Panel-Recht *Bannen* hat,
die letzten Aufträge nur, wer *Audit* hat (Preset `admin`), und die Rollen-/Personen-Zuordnungen nur
Discord-Administratoren – sonst zeigt die Seite dort einen Hinweis statt Daten. Die Kennzahlen
(z. B. Anzahl aktiver Sperren) sind für alle mit Seitenzugriff sichtbar.

Bot-Owner und Allowlist-Nutzer von WebCore dürfen alle Aktionen (für die Anmeldung im Live-Panel
zählen aber immer die echten Discord-Rechte). Jede Änderung landet im **WebCore-Audit-Log** und
zusätzlich im **Audit-Kanal** des Cogs (mit dem Zusatz „(Dashboard)“). Beim Aktivieren des
Lockdowns werden – wie beim Befehl – alle offenen Aufträge verworfen.

## Daten

Aktionen, Bans, Notizen, Sessions und das Protokoll liegen in einer SQLite-DB im
**Red-Datenordner** des Cogs (`…/cogs/AdminPanel/adminpanel.sqlite3`, Backups daneben in
`backups/`, die letzten 14 werden behalten). Beim ersten Laden wird eine DB vom früheren
Speicherort (Code-Ordner) automatisch übernommen; die alte Datei bleibt als Sicherung liegen.

Umgebungsvariablen (`ADMINPANEL_API_KEY`, `ADMINPANEL_WEB_PORT`, `ADMINPANEL_PUBLIC_URL`,
`ADMINPANEL_MONEY_MAX`, `ADMINPANEL_ITEM_MAX`) sind nur noch Vorgaben – per Befehl gesetzte
Werte haben Vorrang.
