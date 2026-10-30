## 29.10.2026 – Support v2.2.2 / AP-Bridge 1.2.2

- Konten zeigen bei exakt zugeordneten Charakter-IDs den Charakternamen in Klammern; Firmen- und Fraktionskonten behalten ihre eigene Kennung. Die Zuordnung erfolgt in einer gemeinsamen Leseabfrage.
- Eine Rechteänderung während einer Spielersuche gibt die Suche wieder frei; verspätete Antworten können eine neue Suche nicht überschreiben.

- Charakter-/Account-/CID-Suche mit Namensteilen, Unicode und literalem Wildcardtext.
- Discord-Benutzer-/Anzeige-/Globalname und ID nur aus gebundener Guild; Charaktere ueber echten Qbox-userId-Schluessel. Mehrere Charaktere bleiben getrennte auswaehlbare CID-Zeilen.
- Begrenzte manuelle Suche, keine Anfrage beim Tippen, keine unbelegte Offline-Namenszuordnung; Rollen-/Session-/Profilfences und alte Bridgeantworten abgesichert.
- Statistik-JSON-Decodes innerhalb bestehender SQL-Bloecke zeit-/zeilenbegrenzt unterbrechen; alle Summen erhalten. Fuenf-Minuten-Katalog unveraendert, keine behauptete Live-Hitchursache.
- Vorherige v2.2.1-Lifecycle-/OAuth-Korrekturen bleiben erhalten. Optionale Indizes nur separater bewusster MariaDB-Import, kein automatisches DDL.

## 29.10.2026 – Support v2.2.1, gezielter Start-/Login-Patch

- Belegter Webport: fehlgeschlagene Site abmelden, neuer Listener je Versuch, Runner bei endgültigem Fehler oder Abbruch bereinigen. Kein falscher Laufstatus nach einem fehlgeschlagenen Bind.
- Web-/Backupaufgaben erst im Cog-Ladehook starten; beim Entladen abbrechen und abwarten. WebCore-Abmeldefehler dürfen den Port nicht festhalten.
- Discord-OAuth bevorzugt aktuell berechtigte Guilds mit aktiv gebundenen Profilen. Unkonfigurierte berechtigte Guilds bleiben Setup-Fallback; Profilwahl und alle bisherigen Rechteprüfungen bleiben erhalten.
- Buildmarker v2.2.1. Sieben Python-Module, 17 tatsächliche Lifecycle- und 10 tatsächliche OAuth-Callbackprüfungen offline bestätigt. Kein automatischer NAS-/Bot-/FiveM-Eingriff und keine Datenbank- oder Profilmigration.
- Der frühere öffentliche NAS-Altstand aus der Messung 12:41 ist historisch. Spätere vom Benutzer gelieferte normalisierte Quellhashes bestätigten v2.2; aktuell sichtbare Profile/Spieler wurden durch den gezielten Guild-Login bestätigt. Dieser neue Patch ist vor der separaten Installation noch kein geladener NAS-Build.

## 29.10.2026 – Support v2.2, Releaseprüfung

- Veraltete Fahrzeug-, Inventar- und Aktenantworten an den sichtbaren Charakter und das aktuelle Server-/Rechteprofil gebunden.
- Alte Bannaktionen/Notizentwürfe beim Aktenwechsel geleert; parallele Notizklicks während des Speicherns gesperrt.
- Fehlerhafte/unbestätigte Leseergebnisse zeigen keine falschen leeren Daten oder Diagnoseerfolge mehr.
- Fehlende Geldsummen werden nicht als 0 und unbekannte Firmen-/Fraktionssummen nicht als bestätigter Gesamtwert angezeigt.
- Fahrzeugsuche mit echter Suchart, exakter persistenter ID und Unterstützung einstelliger IDs; passende Bridge erforderlich.
- Bestehende Fahrzeuglisten zeigen ID und senden beim Einparken ID/erwartetes Kennzeichen. Fehlende ID sperrt den Listenbutton; Rechte bleiben unverändert.
- Garagenkatalog erholt sich nach einer leeren Erstantwort mit begrenzter Wiederholung. Kein zusätzlicher globaler Poll, kein fester „downtown“-Standard.
- Alte Profilantworten können neue laufende Aufträge nicht aus der Doppelklicksperre löschen; veraltete Discord-Mitgliedersuche verworfen.
- Mobile Tabellen begrenzt, Buildmarker v2.2 und bestehende Cache-Schutzheader erhalten.
- Vollständige Quellsicherung, Python-/SQLite-/Browserprüfungen; verpflichtende Bestands-/Profilkonfiguration vor Bereitstellung dokumentiert. Öffentliche NAS-Lesemessung zeigte noch ursprüngliche Oberfläche; kein tatsächliches NAS-Update oder Reload durch diesen Quellbuild.

## 29.10.2026 – Oberfläche eindeutig erkennen

- Kleine Buildkennung auf Loginseite und in Server/Setup-Diagnose.
- Bot-Owner-Lesebefehl `ap version` für geladenen Modulhash und HTML-Hash,
  ohne Geheimnisse, Pfade oder Profil-/Datenbankänderungen.
- HTML nicht zwischenspeichern; PWA-Manifest/Service Worker revalidieren;
  Service-Worker-Aktualisierung ohne HTTP-Cache anfordern.
- Eigene Paneloberfläche und WebCore-Verwaltungsseite ausdrücklich getrennt.
- Kein FiveM-, Bridge- oder Bot-Neustart durch den Quellbuild.

# Changelog

## 28.10.2026 – Supportausbau v2, Testbuild

- Servergetrennte Supportfälle mit Nummer, Übernahme, Zuweisung, Übergabe,
  Status, Kommentaren und authentifizierten Bildanhängen.
- QA-Bug-Referenz und gespeicherte Berichte aus tatsächlich abgeschlossenen
  Leseaufträgen; kein frei erfundener Clientbericht.
- Gemeinsame Fahrzeugakte für Privat-, Leasing- und Fraktionsfahrzeuge,
  persistente ID, Halterlink, Garage und gekennzeichnete Standortbeobachtung.
- Geführte Leseprüfungen für Schlüssel, Kofferraum, Kraftstoff und Nebenjobs.
- Echte Dev-/Live-Isolation für SQLite/Queue/State/Keys/Medien, explizite
  Profilwahl in Web, Discord und WebCore; Schlüssel nicht im Browser.
- Additive Supporttabellen und actions.profile_queue_hold; alte pending-Aufträge
  bleiben erhalten, werden beim Profilupgrade aber nicht automatisch ausgeführt.
- ap_bridge 1.2.0 mit Profiltransport und begrenzten neuen Leseaktionen.
- Keine Ressourcen-/Bot-Neustarts oder tatsächliche Dev-/Live-Datenmigration
  durch die Entwicklungsarbeit. Quellcode vorher gesichert.

### Grenzen und Installation

Legacy-Bestand wird nicht automatisch auf Dev oder Live verschoben. Profile und
separate Schlüssel vor Nutzung konfigurieren; Anleitung befolgen. Kein echter
Discord-/FiveM-Test, keine automatische Reparatur/Freigabe/Auszahlung. Nicht
vorhandene Leseexporte bleiben unbekannt (insbesondere Schlüsselablauf, private
Kofferraumsperren und Nebenjob-Abrechnungsjournale). QR-/Weblink zur QA-App ist
nicht erfunden; die gespeicherte Bug-ID bleibt eine Referenz.

## 28.10.2026 – DNP Admin Zentrale, Testbuild

- DNP-Blau, klare Navigation, mobile Spieleransicht und aufklappbare Werkzeuge.
- Aktualisieren und lokales Abmelden; sichtbare Fehler, Tastaturfokus und Dialoge.
- Exklusive Statusabfrage mit Backoff; Pause im Hintergrund/offline, lokale Filter.
- Keine API-/Spielerdaten im PWA-Cache und keine extern geladenen Schriftarten.
- Ergebnisse in State, Historie, Audit und Discord-Status nach Aktionsrecht gefiltert.
- Terminale Rückmeldungen atomar und wiederholbar; Konflikte ändern keine Abschlüsse.
- Ban und erster Abschluss gemeinsam gespeichert; Retry verlängert keine Ban-Frist.
- Einmaliger Audit-Claim mit sichtbarer unbestätigter Zustellung, ohne Auto-Neuversand.
- Tatsächliche ap_bridge-1.1-Healthfelder mit unbestätigtem Fallback für ältere Bridges.
- Keine neuen Adminfähigkeiten, Rollenänderungen oder erzwungene Queuefreigabe.

### Additive SQLite-Migration

Beim nächsten Laden ergänzt init_db fehlende actions-Spalten: target_name,
callback_fingerprint, result_review_required, result_review_reason, audit_delivery,
audit_claimed_at und audit_completed_at. Keine Löschung oder Neubefüllung.
Legacy-Abschlüsse ohne Fingerprint werden nicht nachträglich ausgeführt oder erneut
ausgezahlt/gesendet. Zusätzliche Spalten können bei einer Rücknahme bestehen bleiben.

### Installation und Abnahme

Quellcode vorher gesichert. Vor dem normalen Cog-Laden auch Reds echte Daten und
Konfiguration sichern. Kein Live-/Bot-Neustart wurde durch diese Arbeit ausgeführt.
33 Backend-, 87 UI- und 44 DTO-Browserprüfungen mit isolierten Testdaten bestanden.
Realer Discord-Login, WebCore-Anbindung, Bridge und PWA-Installation noch offen.

Fahrzeuglisten zeigen weiterhin den bisherigen privaten Fahrzeugbestand; DNP-
Fraktions-/Leasingadapter sind nicht ergänzt. Die bestehende Firmenstatistik kann
in ihrer Fallback-Abfrage persönliche Konten mitrechnen; Schema gesondert prüfen.
Der Cog ist weiterhin für einen FiveM-Server ausgelegt. Kein gemessener Lag-Fix.
