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
