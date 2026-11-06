# FiveM-Adminpanel

## Fraktions-Discord vom 06.11.2026 – vorbereiteter Testbuild

Aktueller Paketstand: `2026-11-06-support-v2.3.1`. Ohne individuelle Ausnahme sind
Rollen sowie private Text- und Sprachkanäle je Fraktion standardmäßig aktiv.
Die Auswahl bleibt unter **Editor-Tablet → Fraktionen → Discord**. Ebenso ist ein
gültig gebundenes Dev-/Live-Profil standardmäßig eingeschaltet; eine ausdrücklich
gespeicherte Abschaltung bleibt erhalten. `legacy`, falsche Guild-Zuordnung,
geteilte Dev-/Live-Guilds oder fehlende Bot-Rechte bleiben gesperrt.

Eine vollständige, vom Server bestätigte Auflösung löscht ausschließlich die
nachweislich von dieser Anbindung erstellte Fraktionsrolle. Fremde zugeordnete,
geschützte, veränderte oder weiterhin benötigte Rollen bleiben bestehen.
Kanäle werden archiviert, ihr Verlauf bleibt erhalten. **Aus** löscht keine Rolle.
Einrichtungsdetails und Abnahme: [FACTION-DISCORD.md](FACTION-DISCORD.md).

Quell-/Testpaket; kein NAS-Bot-Neuladen und keine tatsächliche Discord-Aktion durch
die Entwicklung. Der Betreiber prüft den Stand zuerst in einer getrennten Guild.


Webpanel und Discord-Befehle für die gemeinsame FiveM-Aktionswarteschlange. **Dev, Live und Altbestand sind getrennte Serverprofile**. Daten, Aktionen und Fotos bleiben im ausgewählten Profil.

## Schnellstart

1. Vollständigen Cog im Bot installieren/laden; vorhandenen Cog-Datenordner vorher sichern. `[p]ap version` zeigt den geladenen Build.
2. Als **Bot-Owner in der vorgesehenen Discord-Guild**: `[p]ap profile bind live Mein Live-Server` (für Tests entsprechend `dev`). Ein bereits anders gebundenes Profil wird nicht automatisch umgebunden. `legacy` bezeichnet den vorhandenen, zunächst unzugeordneten Altbestand.
3. Den passenden Schlüssel **außerhalb Discords** als Umgebungsvariable des Bot-Prozesses konfigurieren, z. B. `ADMINPANEL_LIVE_KEY`. Dann `[p]ap profile keyenv live ADMINPANEL_LIVE_KEY`. Die passende Bridge auf demselben FiveM-Server konfigurieren. Keywerte niemals in Chat oder DM schreiben; `[p]ap config key` erzeugt oder zeigt keinen Schlüssel.
4. `[p]ap config url https://panel.deinedomain.tld` setzen. HTTPS über Reverse-Proxy verwenden; läuft er auf demselben Rechner, `[p]ap config bind 127.0.0.1` verwenden. Geänderte Bind-Adresse/Ports werden beim regulären Cog-Neuladen wirksam.
5. Discord-Administratoren vergeben Rollen-Presets mit `[p]ap roles set support @Support` oder verwalten einzelne Funktionsrechte im Live-Panel unter **Berechtigungen**. Im WebCore gelten zusätzlich die Seitenrechte Ansehen/Bedienen/Bearbeiten.
6. Als berechtigtes Mitglied `[p]ap server live` auswählen. Im WebCore ebenfalls **Guild und Serverprofil ausdrücklich auswählen**. Danach im Dashboard anmelden oder `[p]ap login` verwenden; Profilwahl und Rollen werden bei Aktionen erneut geprüft.
7. Zuerst lesend prüfen: `[p]ap config show`, `[p]ap diag`, Serverzustand und Aktionsprotokoll. Ein Auftrag gilt erst nach passender Serverbestätigung als ausgeführt. Bei unklarem Ergebnis zunächst prüfen und keine Aktion blind wiederholen.

Die zur vorhandenen Installation passenden Bridge-/FiveM-Dateien gemeinsam aus dem jeweiligen Release übernehmen. Der Cog führt keine automatische Live-Installation oder Serverneustarts aus. Fraktions-Discord startet bei gültiger Profileinrichtung ohne ausdrückliche Abschaltung automatisch: [FACTION-DISCORD.md](FACTION-DISCORD.md).

## Alltag im Panel

- **Bedienen** im WebCore erlaubt Anmelden, einzelne Sperren aufheben und Not-Aus; dafür gelten weiterhin die passenden Panel-/Administratorrechte.
- Einstellungen und Rechte-Zuordnungen brauchen **Bearbeiten**, Rechteverwaltung zusätzlich Discord-Administrator oder Bot-Owner.
- Neue Supportfälle unter **Support** anlegen, übernehmen/übergeben, kommentieren und Fotos hinzufügen. Änderungen beziehen sich immer auf das bestätigte Profil und die aktuelle Fallversion.
- Not-Aus sperrt Aktionen und verwirft offene Aufträge im ausgewählten Profil. Das Aufheben führt verworfene Aufträge nicht nachträglich aus.

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

## Profile und Konfiguration

`[p]ap profile bind <legacy|dev|live> [Name]` bindet ein Profil als Bot-Owner an die aktuelle Guild. `[p]ap profile keyenv <Profil> <Variablenname>` ordnet einen vorhandenen ENV-Namen zu. `[p]ap server [Profil]` zeigt/ändert die persönliche Auswahl. Es gibt keine automatische Dev-/Live-Auswahl und keinen Rückfall auf ein anderes Profil.

## Datenlöschung

Die aktuellen SQLite-Datenbanken liegen im Red-Cog-Datenordner, Profilkopien unter `profiles/<Profil>/`, Supportfotos profilbezogen unter `support_media/`. Red-Datenlöschanfragen entfernen anhand der **gespeicherten exakten Discord-ID** eigene Supportfälle samt Beiträgen und Fotos. In fremden Fällen werden eigene Texte/Berichte/Urheberschaft anonymisiert, eigene Fotos entfernt und die eigene Zuständigkeit aufgehoben. Betroffene Antwortcaches und gespeicherte persönliche Profilwahl/Einzelzugriffe werden bereinigt. Login-Tokens und Sitzungen werden in Anmeldung und Profilkopien ungültig. Verifizierte Aktionsautor-IDs werden anonymisiert; Status, Sperren und Ausführung einer Aktion werden dadurch nicht verändert.

Fehlgeschlagene Fotolöschungen bleiben ohne Nutzerzuordnung für einen erneuten Bereinigungsversuch erfasst. Dateipfade werden auf den jeweiligen Fotoordner begrenzt. Spielidentitäten werden nicht aus Namen oder CitizenIDs abgeleitet. Bereits vorhandene Datenbanksicherungen und Nachrichten im Discord-Auditkanal verwaltet der Betreiber nach seiner Aufbewahrungsregel.

## Versionshistorie und Details

Die vollständigen bisherigen Einrichtungs-, Release- und Abnahmehinweise stehen unverändert im [CHANGELOG.md](CHANGELOG.md). Aktuelle Fraktionsfunktionen (standardmäßig aktiv bei gültiger Einrichtung): [FACTION-DISCORD.md](FACTION-DISCORD.md).
