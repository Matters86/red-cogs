# Fraktionsrollen und private Bereiche – Testbuild 08.11.2026

Paketbuild `2026-11-08-support-v2.3.3`, Koordinator `faction-discord.4`.
Vorbereitet und isoliert geprüft; **nicht auf dem NAS-Bot aktiviert und kein
echter Discord-/Ingame-Test**. Die vorhandene Support-Zentrale bleibt erhalten.

## Bedienung

Die tägliche Einrichtung gehört ins **Editor-Tablet → Fraktionen → Discord**.
Ein Server-Editor wählt je Fraktion:

- Aus, automatisch eine Rolle mit dem Fraktionsnamen anlegen oder eine vom
  Discord-Administrator zuvor freigegebene bestehende Rolle verwenden.
- Privaten Textkanal und/oder Sprachkanal erstellen.
- Automatische Kategorie **DNP · Behörden** für `state`, **DNP · Crime-Fraktionen**
  für `crime`. `media` und andere Kategorien verwenden weiterhin **DNP · Fraktionen**.
  Eine ausdrücklich gewählte, zuvor freigegebene Kategorie bleibt unverändert.

Die Gruppen stammen ausschließlich aus der vollständigen bestätigten Serverquelle,
nicht aus Rollen-/Fraktionsnamen. Für die zwei neuen Gruppen werden getrennte
Erstellungsbelege und IDs gespeichert. Eine alte eigene Sammelkategorie bleibt
bestehen; ihre bisherigen eigenen Text-/Sprachkanäle behalten ihre IDs und ihren
Verlauf und werden beim bestätigten Abgleich in die passende Gruppe verschoben.
Nicht beobachtbare unbenutzte alte Kategorien werden nicht neu erstellt. Eine
fehlende tatsächlich ausgewählte Gruppe bleibt dagegen zur Prüfung angehalten.

Normale Mitglieder und Fraktionsleiter erhalten dadurch kein Editorrecht.
Ohne individuell gespeicherte Ausnahme starten State- und Crime-Fraktionen mit
automatischer Rolle, privatem Text- und Sprachkanal. Eine bereits ausdrücklich
gespeicherte Abschaltung bleibt bestehen. Die Discord-Rolle ist
keine Vergabe von Ingame-Admin- oder Server-Editor-Rechten.

## Einmalige Bot-Einrichtung

1. Den vollständigen bisherigen Cog-Ordner und die Red-Daten vor der Übernahme
   sichern. Zusammengehörigen neuen Cog, AP-Bridge und Fraktionscode aus demselben
   Updatepaket verwenden. Keine alten Profil-SQLite-Dateien überschreiben.
2. Betreiber lädt den vollständigen Cog regulär neu. `[p]ap version` muss
   `2026-11-08-support-v2.3.3` zeigen. `[p]` ist euer vorhandenes Bot-Präfix.
3. Bot-Owner bindet ein ausdrückliches Profil an die richtige Guild:
   `[p]ap profile bind live DNP Live`. Schlüssel nur über die vorhandene
   Umgebungsvariablen-Konfiguration zuordnen; keine Schlüssel in Chat posten.
   Das bestehende `legacy` bleibt für Discord-Schreibaktionen gesperrt.
4. Der FiveM-Teil bleibt auf **Dev ausgeschaltet** (`set fraktion_discord_enabled 0`).
   Auf Live ausdrücklich `set fraktion_discord_enabled 1` und das vorhandene
   `adminpanel_profile live` verwenden. Schlüssel-/Guildzuordnungen unverändert
   erhalten; keine komplette Dev-server.cfg oder Profildatenbank nach Live kopieren.
   Die bisherigen getrennten Bot-Profile bleiben erhalten, aber Dev sendet keine
   Fraktionsaufträge. Eine gespeicherte Profil-Guildzuordnung wird nicht umgebogen.
5. Der Bot benötigt **Rollen verwalten** und **Kanäle verwalten**. Seine höchste
   Rolle muss über allen verwendeten Fraktionsrollen stehen. Administratorrecht
   wird für den Bot nicht verlangt.
6. Ein gültig gebundenes, isoliertes Dev-/Live-Profil ist standardmäßig aktiv,
   sofern keine ausdrückliche Abschaltung gespeichert ist. Ein fehlender Schalter
   ist dabei die vorgesehene Standardeinstellung, keine fehlende Freigabe.
   War das Profil bewusst ausgeschaltet, kann ein Discord-Administrator dieser
   Guild es mit `[p]ap factiondiscord live enable` wieder einschalten.
   Ungültige Einstellungen, Legacy, geteilte Guilds oder fehlende Bot-Rechte
   bleiben gesperrt. Ohne passende Guild-/Bridge-Einrichtung entsteht nichts.
7. Nur wenn bestehende Objekte verwendet werden sollen:
   `[p]ap factiondiscord live allowrole ROLLEN_ID` bzw.
   `[p]ap factiondiscord live allowcategory KATEGORIE_ID`.
   Erst dann erscheinen sie im Editor-Dropdown. Eine namensgleiche Rolle wird
   niemals automatisch übernommen. Automatisch erstellte Rollen haben keine
   zusätzlichen Guild-Berechtigungen.
8. Ingame zuerst eine einzelne Testfraktion konfigurieren, Bestätigung abwarten,
   anschließend die untenstehenden Tests im getrennten Test-Discord durchführen.

Discord-Administratoren konfigurieren hier nur den sicheren Rahmen; die
Fraktionszuordnung bleibt im Editor. Bot-Owner ohne Administratorrecht in der
betreffenden Guild kann die Freigaben nicht über diesen Befehl ändern.

### Weitere Befehle

`[p]ap factiondiscord live status` zeigt den Profilstatus. `disable` pausiert
sämtliche Discord-Änderungen, ohne Rollen oder Verlauf zu löschen. Für normale
Fraktionsdeaktivierung im Spiel den Modus **Aus** verwenden: Dann zieht der
bestätigte Abgleich seine zugeordneten Mitgliedsrollen zurück und schließt die
eigenen Kanäle. `denyrole ID` / `denycategory ID` nehmen Katalogfreigaben zurück.

`protect ROLLEN_ID` schützt weitere Rollen, insbesondere eine bestehende
**Server-Editor-Rolle** oder andere extern ausgewertete Rechte-Rollen, auch wenn
diese in Discord selbst keine besonderen Rechte haben. `unprotect ID` hebt nur
diesen zusätzlichen Schutz auf. Rollen aus dem Panel-`role_map`, verwaltete
Integrationsrollen, `@everyone`, Rollen oberhalb des Bots und privilegierte Rollen
bleiben unabhängig davon gesperrt. Bestehende Rollen nie gleichzeitig für externe
Administrationsrechte und Fraktionsmitgliedschaft verwenden.

Bei bekannten Fehlern gibt es acht Versuche mit wachsender Pause bis 15 Minuten.
Danach bleibt der Fehler zur Prüfung stehen. Nach Behebung kann ein
Discord-Administrator `retry` ausführen. Das setzt nur diese Wartezeiten zurück,
**keine unklaren Erstellungsbelege**.

### Unklarer Ausgang einer Erstellung

Vor jeder Rolle/Kategorie/Kanal-Erstellung wird ein Beleg gespeichert. Bei einem
Timeout, Prozessabbruch oder unklaren HTTP-Ergebnis wird nicht nach Namen gesucht
und nicht erneut erstellt. Status `create_result_unknown` verlangt Prüfung im
Discord-Auditlog. Ein sicher abgelehnter HTTP-4xx-Aufruf darf nach Fehlerbehebung
erneut versucht werden; ein unklarer 5xx/Transportfehler bleibt gesperrt.

Wenn das im Audit bestätigte Objekt vorhanden ist, kann der Discord-Administrator
die genaue ID zuordnen:

`[p]ap factiondiscord live resolve FRAKTIONS_ID role|text|voice OBJEKT_ID`

Für eigene Kategorien lautet die Fraktions-ID `0`: `category_state` für
**DNP · Behörden**, `category_crime` für **DNP · Crime-Fraktionen**, `category` für
die bestehende Sammelkategorie. Beispiel nur nach Auditbestätigung eines bereits
unklaren Erstellungsbelegs:
`[p]ap factiondiscord live resolve 0 category_state KATEGORIE_ID`.
Kein neuer Erstellungsversuch bei einem unklaren Beleg und keine Übernahme nach Namen.
Nur offene Erstellungsbelege und passende sichere Objekte werden akzeptiert;
keine automatische Übernahme nach Namen. **Keine fremden vorhandenen Kanäle
zuordnen**: Der Abgleich ersetzt bei eigenen Kanälen ausdrücklich alle
Zugriffsüberschreibungen. Ist kein Objekt bestätigt, den Beleg zur manuellen
Betreiberprüfung erhalten; nicht durch Löschen der Bot-Daten umgehen.

## Mitgliedschaften und Schutz bestehender Inhalte

Die vertrauenswürdige Serverquelle liefert einen vollständigen, stabil
versionierten Stand über alle Charaktere eines verknüpften Discord-Kontos.
Hauptfraktion und ausdrücklich genehmigte weitere Mitgliedschaften zählen;
eine bloße Dienstrolle oder ein früheres Government-Amt genügt nicht.

Ausloggen, Dienstende und Wechsel des aktiven Charakters löschen keine echte
Mitgliedschaft. Eine ausdrücklich im Editor gewählte und vom Discord-Administrator
freigegebene bestehende Fraktionsrolle wird für **aktuell bestätigte Mitglieder**
in die Verwaltung übernommen, auch wenn diese Rolle vorher manuell zugewiesen
wurde. Bei späterer Entlassung entfernt der Abgleich sie. Eine Rolle, die mehreren
Mitgliedschaften entspricht, bleibt erhalten, solange mindestens eine davon gilt.
Der Start durchsucht nicht pauschal alle Discord-Mitglieder: Manuelle Empfänger,
die nicht als aktuelle Mitglieder im bestätigten Bestand stehen, und sämtliche
anderen Rollen bleiben unangetastet. Bereits vor der Einführung falsch vergebene
Rollen solcher Nichtmitglieder müssen separat geprüft werden.

Private Text- und Sprachkanäle verwenden ein eigenes vollständiges
Überschreibungsschema: `@everyone` sieht/verbindet nicht. Nur die zugeordnete
Fraktionsrolle, die ausdrücklich konfigurierte Verwaltung und der technisch
benötigte Bot erhalten Zugriff. Andere Fraktionen und gewöhnliche Spieler
erhalten keinen Zugang. Fremde Rollen aus einer öffentlichen Kategorie werden
nicht geerbt; diese vorhandene Kategorie selbst wird nicht verändert.
Discord-Administratoren umgehen Kanalüberschreibungen nach Discord-Regeln.

Für Live ist Marcels Verwaltungsrolle `1497218321660248165` der Standard, wenn
noch keine eigene Verwaltungsrollen-Liste gespeichert ist. Der Name kann sich
ändern; maßgeblich bleibt ausschließlich die Rollen-ID. Fehlt diese Rolle in
der gebundenen Guild, pausiert der Abgleich mit `management_role_unavailable`;
es wird keine Ersatzrolle erstellt und keine Rolle nach Namen übernommen.
Dev übernimmt diese Live-ID nicht: Dort eine eigene Test-Verwaltungsrolle angeben.
Eine ausdrücklich gespeicherte leere Liste bleibt leer.

Nur ein Discord-Administrator der gebundenen Guild kann die Verwaltungsrollen
über den Bot ändern:

- `[p]ap factiondiscord live allowmanagement ROLLEN_ID` ergänzt eine bestätigte
  vorhandene Rolle; für Dev entsprechend `dev` verwenden.
- `[p]ap factiondiscord live denymanagement ROLLEN_ID` entfernt sie. Wird die
  voreingestellte Live-ID entfernt, wird ausdrücklich eine leere Liste gespeichert;
  der Standard kommt beim nächsten Start nicht zurück.
- `[p]ap factiondiscord live status` zeigt auch die Verwaltungsrollen-IDs.

Höchstens 32 Verwaltungsrollen je Profil; `@everyone`, Integrationsrollen,
ungültige IDs oder doppelte Einträge werden abgelehnt. Es werden keine Rollen
automatisch aus Support-/Panelrechten abgeleitet. Server-Editoren können diese
Verwaltungsrollen nicht über das Spiel ändern. Verwaltungsrollen werden niemals
als Fraktionsmitgliedschaft vergeben, entfernt, umbenannt oder bei einer
Fraktionsauflösung gelöscht. Sie können über der Botrolle stehen, weil der Bot
ihre Mitgliedschaft und Guild-Rechte nicht verwaltet.

Bei deaktivierten/aufgelösten Fraktionen verlieren Fraktionsmitglieder den
Kanalzugriff. Die Verwaltung behält lesenden Archivzugriff auf Text/Verlauf;
Schreiben sowie Betreten/Sprechen im archivierten Voice bleiben für sie gesperrt.
Discord-Administratoren behalten ihren nativen Vollzugriff. Der Bot gleicht auch
bereits erstellte eigene Kategorien und Kanäle nach einer Verwaltungsänderung ab.
Vor jeder Kanaländerung werden die aktuellen vertrauenswürdigen Einstellungen
erneut ausgewertet; veraltete Rechte werden nicht aus einer wartenden Anfrage
zurückgeschrieben.
Eigene Kanäle werden bei Abschaltung oder vollständiger Auflösung archiviert/
geschlossen; der Verlauf wird nicht gelöscht. Eine einfache Deaktivierung oder
der Modus **Aus** löscht die Rolle nicht. Erst eine vom Server ausdrücklich und
dauerhaft bestätigte vollständige Fraktionsauflösung veranlasst die Löschung
der nachweislich von dieser Anbindung erstellten Rolle. Eine nur zugeordnete
bestehende Rolle bleibt erhalten.

Das Löschen ist an die gespeicherte exakte Rollen-ID gebunden. Der Worker prüft
vorher über die REST-Rollenliste, dass es sich weiterhin um die eigene unveränderte
Rolle ohne zusätzliche Guild-Rechte handelt. Geschützte Rollen, nachträglich
veränderte Rechte, Bot-Hierarchie und Verweise anderer noch bestehender Fraktionen
verhindern die Löschung. Dabei zählen auch ausgeschaltete Fraktionen.
Ein fehlender Fraktionseintrag, Dienstende, Ausloggen, ein leerer/unbestätigter
Bestand oder fehlender Bot-Cache gelten niemals als vollständige Auflösung.

Der Löschauftrag wird vor dem DELETE dauerhaft gespeichert. Bei unklarem Ausgang
bleibt die genaue ID vorgemerkt: Eine neue REST-Prüfung kann das bestätigte Fehlen
abschließen oder bei weiterhin bestätigter Auflösung dieselbe ID idempotent
erneut löschen. Es wird dabei keine Ersatzrolle angelegt. Ein aufgezeichneter
DELETE mit 404 bestätigt allein noch keine Rollenlöschung: Ein nicht mehr
erreichbarer Discord-Server könnte dieselbe HTTP-Antwort verursachen. Auch hier
bestätigt erst die vollständige neue Rollenliste der richtigen Guild das Fehlen.
Ein aufgezeichneter
Löschvorgang blockiert auch die Wiedererstellung durch einen später auftauchenden
alten Auto-Eintrag. Eine bereits gesendete Anfrage lässt sich bei gleichzeitigem
Fraktionswechsel nicht zurückholen; es gibt keine behauptete Atomarität über
FiveM, SQLite und Discord hinweg.

## Technik, Grenzen und Wiederherstellung

- Das vorhandene authentifizierte `/api/bridge/sync` trägt `faction_discord`.
  Keine neue öffentliche Provisionierungsroute, kein vom Spiel frei wählbares
  Guild-Ziel und keine Kennwörter/Tokens im Snapshot.
- Schema 1: vollständiger Snapshot mit `generation`, `complete:true`, `factions`
  inklusive verschachtelter `config` und `memberships` je Discord-Konto.
  Höchstens 128 Fraktionen, 4096 Konten und 16384 Mitgliedschaftspaare.
- `{schema:1,complete:false,code:...}` pausiert gespeichert. Fehlende/trunkierte
  Identitäten, Generation-Rückschritt oder widersprüchliche Wiederholung werden
  nicht als leere Mitgliedsliste verarbeitet.
- Nach jedem Botstart muss ein frischer vollständiger Serverstand ankommen.
  Ohne gesunden Vollsnapshot innerhalb 120 Sekunden pausiert der Worker. Der
  persistierte Bestand allein löst nach einem Neustart keine Änderungen aus.
- Ein Worker, alle fünf Sekunden, höchstens zwölf externe Arbeitsaufrufe und
  32 geprüfte Kontenpaare pro Profilrunde. Rollen-/Kanal-Katalog aus Bot-Cache,
  höchstens einmal pro Minute neu aufgebaut; keine Massensuche aller Mitglieder.
- Rollen/Kategorien/Kanäle werden mit einem einzelnen HTTPS-POST über den bereits
  angemeldeten Bot-Kontext erstellt, mit festem Discord-v10-Ziel, abgeschalteten
  Redirects, 15 Sekunden Timeout und Beachtung von Bucket-/Retry-After-Pausen.
  Das umgeht ausschließlich die SDK-interne Wiederholung nicht idempotenter
  Erstellungen nach 5xx. Es werden keine Tokens aus Dateien gelesen oder geloggt.
  Die bekannte Session-Struktur von discord.py ist erforderlich; bei unbekannter
  Struktur wird mit `single_attempt_transport_unavailable` abgebrochen. Diese
  Grenze muss beim echten NAS-Cog-Test geprüft werden. Andere Bot-Funktionen und
  der globale SDK-Transport werden nicht ersetzt oder gepatcht.
- IDs, gewünschter Stand, Erstellungsbelege, zugeordnete Rollen, Fehler und
  Pausen liegen in eigenen additiven `faction_discord_*`-Tabellen der vorhandenen
  Profil-SQLite, einschließlich der neuen eigenen Löschbeleg-Tabelle
  `faction_discord_deletions`. Keine Löschung/Änderung bestehender Tabellen. Vorhandene
  Profil-Backups erfassen diese Tabellen mit.
- `lastSyncAt` ist nur ein erfolgreich abgeschlossener Abgleich. Vorbereitung,
  Wartestatus und Fehler werden nicht als erfolgreicher Sync ausgegeben.
- Gleichzeitige Mitgliedschaftsänderung während einer Discord-Antwort kann
  kurzzeitig hinterherlaufen. Vor jedem neuen Schreibaufruf wird der aktuelle
  Stand geprüft; ein bereits ausgeführter Rollenaufruf wird in der nächsten Runde
  anhand des neuen Vollstands korrigiert. Keine behauptete transaktionale
  Atomarität über FiveM, SQLite und Discord hinweg.
- Empfänger außerhalb der Discord-Guild bleiben vorgemerkt und werden mit Pause
  erneut geprüft; die Integration lädt keine komplette Memberliste.

## Tests und noch offene Abnahme

`python tests/test_faction_discord.py` verwendet Fake-Discord und ausschließlich
künstliche temporäre SQLite-Dateien. Keine echten Discord-Aufrufe, Logins,
Serveraktionen oder Bestandsdaten. Der lokale Windows-Testloop benötigt keine
Netzwerk-Sockets; SQLite-Aufrufe laufen im Test inline, im Bot per `to_thread`.

Gesamter Offline-Lauf: `python -m unittest discover -s tests -p 'test_faction_discord*.py' -v`.
Zusätzlich prüfen künstliche HTTP-Sessions, dass eine 5xx-Antwort genau einen
Erstellungsaufruf auslöst, 403/429 begrenzt behandelt werden und Credentials nie
an ein frei wählbares Ziel oder einen Redirect gelangen. AST-Tests führen die
echte neue Cog-Verdrahtung mit Framework-Doubles aus; sie ersetzen keinen echten
Red-Cog-Import auf der NAS.

Offline geprüft: Erstellung nur einmal, Rollenunion, gezielte Entlassung trotz
Fehler einer anderen Fraktion, private ACL auch unter öffentlicher Kategorie,
Archivierung, Namensgleichheit, gefährliche/verbotene Rollen, Profiltrennung,
Generation/Limit-Prüfungen, Pause bei unvollständigen Daten, frischer Stand nach
Neustart, Ablauf nach 120 Sekunden, unbekannte Erstellung, bekannte Ablehnung,
Wiederholung mit Budget und Mitgliedschaftswechsel während laufender Anfrage.

Offen im getrennten Test-Discord mit Betreiber: echter Bot-Cog-Ladevorgang,
Rollenhierarchie, Katalog im Editor, Einladen/Entlassen/mehrere Charaktere,
Text/Voice-Zugriff eines Nichtmitglieds, manuell vorhandene Rollen, spätes
Discord-Beitreten, bestätigter 429-/Netzunterbrechungsfall, Abschaltung/Archivierung
und erneute Aktivierung. Zusätzlich: vollständige Auflösung löscht genau die
eigene Rolle, hält aber Kanalhistorie; **Aus**, deaktivierte Fraktion, vorhandene
Fremdrolle, referenzierte Rolle und unbestätigte Daten dürfen keine Rolle löschen.
Neustart und unterbrochene DELETE-Antwort mit exakt derselben Rollen-ID prüfen.
Erst danach Live-Freigabe durch den Betreiber.

Offizielle Grundlagen: [Discord-Berechtigungen](https://docs.discord.com/developers/topics/permissions),
[discord.py API](https://discordpy.readthedocs.io/en/stable/api.html),
[SDK-HTTP-Implementierung 2.6.4](https://github.com/Rapptz/discord.py/blob/v2.6.4/discord/http.py).
