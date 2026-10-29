# Releaseprüfung 29.10.2026 – Support v2.2

Dieser Quellbuild behebt bestätigte Zuordnungs- und Antwortfehler. Er ist kein Nachweis einer auf der Synology geladenen oder im Spiel getesteten Version. Alle 18 ursprünglichen Cog-Dateien sind vor der Änderung separat gesichert.

## Änderungen

- Fahrzeug-/Inventarantworten und Spielerakten sind an die tatsächlich geöffnete Person gebunden. Späte Antworten dürfen nach Charakter-, Profil-, Rollen- oder Modalwechsel keine andere Akte überschreiben.
- Beim Aktenwechsel verschwinden alte Bannaktionen und fremde Notizentwürfe sofort. Speichern einer Notiz sperrt weitere gleichzeitige Klicks; unklare Antworten werden nicht automatisch erneut gesendet.
- Kaputte oder unbestätigte Leseantworten ergeben eine Fehlermeldung, kein erfundenes leeres Inventar, keine leere Fahrzeugliste und keine erfolgreiche Diagnose.
- Eine fehlgeschlagene Geldsummen-Abfrage wird nicht als 0 angezeigt. Cash/Bank und Messzeit müssen bestätigt sein; ohne bestätigte Firmen-/Fraktionssumme bleibt der Gesamtwert ausdrücklich unbekannt.
- Die Fahrzeugsuche übermittelt ihre tatsächliche Suchart (`query_kind`): persistente ID exakt, Kennzeichenpräfix oder exakte CitizenID. IDs 1 bis 9 funktionieren. Abfragen ohne Suchart bleiben als alter Vertrag kompatibel; die dazugehörige Bridge führt kanonische numerische IDs ebenfalls exakt aus.
- Die vorhandene Spielerfahrzeugliste zeigt die persistente ID und bindet Einparken an ID plus erwartetes Kennzeichen. Ohne bestätigte ID bleibt dieser Listenbutton gesperrt. Das separate Kennzeichenformular bleibt ein serverseitig eindeutig zu prüfender Altpfad. Kein neuer Reparatur-/Berechtigungsweg wurde eingeführt.
- Garagenvorschläge stammen ausschließlich vom ausgewählten Server. Eine anfänglich leere Liste wird frühestens nach 60 Sekunden über den vorhandenen Aktualisierungsweg erneut geprüft. Es gibt keinen weiteren Poll-Loop und kein erfundenes Standardziel. Der alte Discord-Standard „downtown“ wurde entfernt; leer bedeutet serverseitige sichere Auswahl.
- Verspätete Profilanfragen entfernen keine neue laufende Doppelklicksperre mehr. Die Discord-Benutzersuche hält ihre Ergebnisse an der aktuellen Eingabe fest. Tabellen bleiben auf schmalen Displays innerhalb ihres eigenen Scrollbereichs.

## Verbindlicher Installations- und Konfigurationsabgleich

1. **Tatsächlich geladene NAS-Kopie bestimmen.** Die öffentliche, rein lesende Prüfung von 12:41 am 29.10. zeigte noch exakt die ursprüngliche Oberfläche vor dem 28.10. (HTML-SHA `d382bdba4af90cc8e272b416958d7c4e40a8f8e177cfca0824e4d415afb57f6c`). Damit war dort alter HTML-Quellstand ausgeliefert; es ist kein Nachweis eines bloßen iPhone-Caches. Development-/Downloader-Ordner und von Red geladener Cog können verschiedene Verzeichnisse sein. Keine NAS-Datei und kein laufender Bot wurden durch diese Prüfung geändert.
2. **Vorher vollständige Sicherung:** geladener Cog, Red-Konfiguration und tatsächlicher Cog-Datenordner einschließlich SQLite/WAL, `profiles`, `support_media` und Sicherungen. Eine neue Ressourcen-ZIP ersetzt keine Red-Datensicherung.
3. **Bestehenden Server zuerst eindeutig zuordnen.** Der vorgefundene Dev-Konfigurationsausschnitt enthielt weder `adminpanel_profile` noch `adminpanel_server_id`. Die alten Daten bleiben daher bewusst im getrennten Bestand `legacy`; es gibt keine automatische Dev-/Live-Übernahme. Vor Aktivierung feststellen, welcher bisherige Server diesen Bestand verwendet. Nur für diesen Bestandsserver bindet der Bot-Owner in der richtigen Discord-Guild beispielsweise `[p]ap profile bind legacy Bestand`. Kein gemeinsames Legacy-Profil unbesehen für Dev und Live verwenden.
4. **Dev und Live bewusst getrennt einrichten:** eigene Profilbindungen, SQLite-Dateien/Queues und getrennte vorhandene Schlüssel-Umgebungsvariablen. Auf FiveM müssen `adminpanel_profile` und `adminpanel_server_id` zum jeweiligen freigegebenen Profil passen. Werte im vorbereiteten Konfigurationsabgleich prüfen; keine Config-Datei blind überschreiben. Schlüsselwerte ausschließlich in der vorgesehenen Bot-/Serverumgebung hinterlegen, niemals in diesem Chat oder Discord posten. `[p]ap profile keyenv` nimmt nur den Namen einer vorhandenen Umgebungsvariable entgegen. Keine Datenbankdateien in ein anderes Profil kopieren, solange ihre Zuordnung unbestätigt ist.
5. **Alte offene Aufträge bleiben erhalten und gesperrt:** Beim Profilupgrade werden frühere `pending`-Aufträge als `profile_queue_hold` markiert und nicht automatisch ausgeführt. Keine pauschale Freigabe/Leerung und kein Rückstart einer alten Cog-Version gegen diese erweiterte DB. Erst tatsächliche Ausführungsbelege prüfen.
6. Nach dem Abgleich den **vollständigen** Cog aus diesem Build in die tatsächlich geladene Red-Kopie aktualisieren; danach den Cog über die normale Red-Verwaltung neu laden. Die passenden Bridge-Dateien dieses gemeinsamen Builds gehören separat auf den richtigen FiveM-Server. Das sichere Einparken und die typisierte Suche hängen von beiden Seiten ab. Das reine HTML-/CSS-Update benötigt selbst keinen FiveM-Neustart.
7. Bot-Owner prüft `[p]ap version`: Build `2026-10-29-support-v2.2`, beim Laden erfasster Modulhash und tatsächlich ausgelieferter HTML-Hash. Die öffentliche Antwort muss `X-DNP-Panel-Build` und `X-DNP-Panel-HTML-SHA256` passend zum Paketmanifest enthalten. Dafür ist kein Schlüssel im Browser nötig. Erst danach die Handyapp neu öffnen und richtige Profilwahl/Rechte prüfen. Kein automatisches Löschen von PWA-, Cookie- oder NAS-Daten.

HTML/API bleiben `no-store`; Service Worker und Manifest müssen revalidiert werden. Die eigene Handyoberfläche kommt aus `panel.html`, nicht aus dem FiveM-Bridgecode. WebCore `/cogs/fivemadmin` bleibt die getrennte Verwaltungsseite mit Link zur eigenen Oberfläche.

## Prüfung und verbleibende Abnahme

Vollständiger Python-Cog mit kontrollierten Red/aiohttp-Grenzen, tatsächliche SQLite-Queue/Profilisolation/Altauftrags-Sperre und die tatsächliche vollständige HTML/JS-Oberfläche wurden offline geprüft. Die Browserfälle decken verspätete Antworten, beschädigte JSON-Ergebnisse, ID-/Kennzeichenbindung, Profilwechsel, Rechtekontext und mobile Breiten ab. Es gab keine Anmeldung auf der NAS, keine Discord-Nachricht, keinen Bot-Reload, keine produktive DB-Aktion und keine Fahrzeugänderung.

Nach Installation bleiben tatsächlicher Red-Dispatcher, passende Profil-/Schlüsselkonfiguration, sichere Bridge-/Garagenabläufe und Ingame-Abnahme mit Privat-/Leasing-/Fraktionsfahrzeug erforderlich. Ein angelegter Auftrag ist weiterhin kein bestätigter Erfolg. Unbestätigte Fahrzeugzustände müssen als Fehler stehen bleiben und dürfen keinen Despawn auslösen.

---

## Update 29.10.2026 – Versionsdiagnose der Oberfläche

Die eigene Handy-/Weboberfläche kommt aus `panel.html` im **tatsächlich geladenen**
Red-Cog. Die AP-Bridge auf FiveM liefert Daten/Aktionen, aber weder HTML noch CSS.
Ein reines Optikupdate braucht daher kein Update oder Neustart des FiveM-Servers.
Der WebCore-Bereich `/cogs/fivemadmin` ist eine getrennte Verwaltungsseite mit dem
zentralen WebCore-Theme; dort ist der Link „Live-Panel öffnen“ relevant.

Die Loginseite und der Bereich Server/Setup-Diagnose zeigen jetzt
„Oberfläche: 29.10.2026 · Support v2.2“. Nur Bot-Owner können mit
`[p]ap version` den beim Laden festgehaltenen Cog-Hash und den aktuellen HTML-Hash
lesen, auch ohne gewähltes Serverprofil. Es werden keine Pfade, Konfigwerte,
Schlüssel, Spielerdaten oder Datenbankinhalte ausgegeben oder verändert.

HTML wird mit `no-store` ausgeliefert, Service Worker und Manifest müssen neu
validiert werden. Die PWA-Registrierung umgeht den HTTP-Cache des Service Workers
und fordert dessen Aktualisierung an. Ein vorgeschalteter Proxy oder ein noch
alter installierter Service Worker ist damit **nicht** als tatsächliche Ursache
nachgewiesen; wirkliche Paneladresse/Instanz und Reload prüfen.

Vor Update echte Red-Daten/SQLite/Fotos/Konfiguration separat sichern. Den ganzen
Cog in der tatsächlich installierten Red-Kopie aktualisieren, anschließend über
die normale Red-Verwaltung neu laden und die Webapp neu öffnen. Development- und
Downloader-Ordner können getrennte Kopien sein. Kein Selbstreload, keine neue
DB-Migration und keine neue Bridgeaktion durch diese Diagnose.

# FiveM-Adminpanel (`fivemadmin`)

## Supportausbau v2 – 28.10.2026

Supportfälle mit Nummer, Zuständigkeit, Übergabe, Kommentaren und Bildern;
QA-Bug-ID als Referenz ohne Duplikat und ohne fremde QA-Rechte. Falländerungen
sind versioniert und wiederholte identische Anfragen erstellen keinen zweiten
Eintrag. Fotos: JPEG/PNG/WebP, höchstens 4 MiB, acht je Fall; authentifizierter
Abruf nur im ausgewählten Serverprofil. Bilder werden erst auf Wunsch geladen.

Fahrzeugakte für private, Leasing- und Fraktionsfahrzeuge mit persistenter ID,
Halterzuordnung, Garage, eindeutiger Runtimebeobachtung und gespeicherter letzter
Position. Registertreffer sind keine Nutzungsberechtigung. Geführte Leseprüfungen
für Schlüssel, Kofferraum, Tanken/Kanister und Nebenjobs liefern bestätigte
Beobachtungen und ausdrückliche unbekannte Punkte. Berichte lassen sich am Fall
speichern. Keine automatische Freigabe, Auszahlung oder Fahrzeugänderung.

Dev und Live sind echte getrennte Profile mit eigenen SQLite-Dateien/Queues,
Bridge-Schlüsseln, Fällen, Medien und Zuständen. Web, Discord und WebCore verlangen
eine explizite Auswahl. Die bisherigen Daten bleiben im unzugeordneten Profil
legacy. Neue Profile übernehmen keine alten Queues oder Bans. Vor dem Laden
unbedingt die beiliegende Einrichtung/Bestandsübernahme lesen.

Bot-Owner bindet ein Profil im gewünschten Discordserver mit
`[p]ap profile bind dev Entwicklung` / `[p]ap profile bind live Live`.
Keys kommen aus separaten Bot-Umgebungsvariablen ADMINPANEL_DEV_KEY und
ADMINPANEL_LIVE_KEY. Niemals Schlüsselwerte in Discordbefehle schreiben.
Discordauswahl: `[p]ap server dev` bzw. `[p]ap server live`; Webauswahl oben.
ap_bridge 1.2.0 braucht den passenden adminpanel_profile-Convar und Schlüssel.

Die bisherigen Support/Moderator/Admin-Presets erhalten die drei Supportrechte;
Editor allein erhält sie nicht. Discord-Guild-Bindung und aktuelle Rollen werden
serverseitig geprüft. Keine Gleichsetzung mit dem Ingame-Server-Editor.

Schemaerweiterungen sind additiv. Frühere pending-Aufträge werden beim erstmaligen
Profilupgrade als profile_queue_hold markiert und nicht automatisch abgearbeitet.
Die alte Cog-Version filtert diese Spalte nicht: alte Version niemals unbesehen
gegen die neue Datenbank starten. Keine manuelle Freigabe von Altaufträgen ohne
Prüfung ihrer Ausführungsbelege. Alte Daten bleiben vollständig erhalten.

Vor Aktivierung vollständigen Red-Cog-Datenordner inklusive support_media,
profiles und Red-Konfiguration sichern. Die tägliche SQLite-Sicherung allein
enthält keine Bilddateien. Ein Prozessabbruch vor dem Foto-DB-Commit kann eine
nicht referenzierte Datei hinterlassen; sie wird nicht öffentlich ausgeliefert.

Lokale Modultests mit temporärer SQLite, tatsächlichen Lua-Modulen und dem
installierten FiveM-JSON-Serializer sowie Browser-Vertragsprüfungen sind vorhanden.
Echter Discord-Login, echte Dev-/Live-Schlüsselkonfiguration und Ingame-Abnahme
stehen aus. LIMIT begrenzt Ergebnismengen, keine garantierte SQL-Laufzeit;
reale Abfragezeiten und Ressourcenlast auf Dev prüfen. Kein gemessener Lag-Fix.

## Update 28.10.2026 – DNP Admin Zentrale

Das Webpanel/PWA hat den blauen DNP-Look, aufklappbare Werkzeuggruppen, eine
touchfreundliche Spieleransicht und lokales Abmelden. Vorhandene Aktionen,
Rollen-Presets und Endpunkte bleiben bestehen. DNP-Hauptfraktionen werden durch
die vorhandenen Job-/Gang-Befehle nicht automatisch neu zugewiesen.

Panelkontakt, Bridgekontakt und gemeldete Ausführungsbereitschaft werden getrennt
angezeigt. DB-Ping ist eine Stichprobe mit Alter, kein dauerhaft gemessener Livewert.
Fehlende Statusfelder älterer Bridges bleiben unbestätigt. Aktualisierung ohne
überlappende Abfragen, mit Fehlerpause und ohne regelmäßigen Abruf im Hintergrund.

Aktionsergebnisse werden in allen geänderten Ausgaben nach dem konkreten Recht
gefiltert. Wiederholte identische Abschlussmeldungen ändern weder Ergebnis noch
Ban-Frist; Widersprüche bleiben prüfpflichtig. Abschluss und Ban werden gemeinsam
gespeichert. Auditversand wird einmal reserviert; nach unbestätigtem Versand oder
Prozessabbruch erfolgt kein blinder Neuversand. Eine Auditnachricht kann deshalb
fehlen und muss geprüft werden. Es gibt keine Exactly-once-Zusage für Discord.

Vor dem Laden: Red-Datenordner/SQLite und Red-Konfiguration zusätzlich sichern;
die mitgelieferte Quellcodesicherung enthält diese laufenden Daten nicht.
SQLite wird beim Laden nur um fehlende Spalten ergänzt; es wird nichts geleert
und keine alte Queue automatisch freigegeben. Keine alte und neue Instanz parallel
starten. Details im CHANGELOG.md und der beiliegenden Installationsanleitung.

Offline getestet: 33 Backendtests mit temporärer SQLite, 87 vollständige
Browserprüfungen und 44 Prüfungen mit tatsächlichen Backend-Testantworten.
Discord-Login, echte Bridgeaufträge, WebCore und PWA-Installation sind noch auf
einer Testinstanz abzunehmen. Kein gemessener FiveM-Hitch-Gewinn behauptet.

Verwaltung eines **FiveM-Servers (QBox)** per Discord-Befehl **und** eigenem Webpanel. Beide
Wege schreiben in dieselbe **Action-Queue**; der FiveM-Server holt die Aufträge über die
Bridge-Resource `ap_bridge` per HTTP ab und meldet das Ergebnis zurück.

- **Support-Aktionen:** Teleport (zu Spieler/Koordinaten), Heilen, Wiederbeleben, Fahrzeuge
  einparken (einzeln oder alle), private Nachrichten, Ansagen.
- **Moderation:** Kick, Ban (Stunden oder permanent), Unban, Team-Notizen und Verwarnungen in
  der Spielerakte, Spielersuche (auch offline).
- **Admin:** Geld und Items geben/nehmen (mit Limits pro Aktion), Job/Gang setzen, Statistiken,
  Audit-Log.
- **Webpanel** (installierbar als App/PWA) mit Tabs Spieler, Wirtschaft, Serverstatus, Kontrolle und
  Aktivitäten; Login per Einmal-Link (`[p]ap login`) oder „Mit Discord anmelden" (OAuth2).
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
Server und auf der Dashboard-Seite mindestens das Recht *Bedienen* (die Anmeldung ist ein Formular-POST
mit CSRF-Schutz). Mit nur *Ansehen* erscheint ein Hinweis auf `[p]ap login`.

**Rechte im Dashboard:** Wer die Seite sieht und was er dort darf, legt der Bot-Owner unter
*Verwaltung → Zugriff & Rollen* fest (WebCore-Rollen-Rechte, pro Server): *Ansehen* = nur lesen,
**Bedienen** = Tagesgeschäft (Im Live-Panel anmelden, Not-Aus, Entbannen), *Bearbeiten* = zusätzlich
Panel-Rechte und Einstellungen. **Zusätzlich** prüft jede Aktion serverseitig dieselben Rechte wie der
passende Befehl bzw. Live-Panel-Endpunkt:

| Aktion | WebCore-Stufe | Zusätzlich nötig |
|---|---|---|
| Im Live-Panel anmelden | Bedienen | irgendein Panel-Recht auf dem Server – wie `[p]ap login` |
| Entbannen | Bedienen | Panel-Recht *Bannen* (Preset `moderator` oder `admin`) – wie `[p]ap unban` |
| Lockdown an/aus (Not-Aus) | Bedienen | Discord-Administrator des Servers – wie `[p]ap lockdown` |
| Panel-Rechte ändern | Bearbeiten | Discord-Administrator des Servers – wie `[p]ap roles`; zusätzlich kann niemand ein Preset vergeben oder entziehen, das mehr Rechte hat als er selbst |
| Einstellungen | Bearbeiten | nur Bot-Owner/Allowlist, weil sie **botweit** gelten |

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
