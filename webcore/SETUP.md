# Gemeinsamer Einrichtungsassistent

Im Dashboard öffnet **Einrichtung** einen gemeinsamen Ablauf für die wichtigsten
Grundeinstellungen. Du brauchst **Bearbeiten** für jedes ausgewählte Modul auf
dem ausgewählten Server. Ansehen oder Bedienen reichen nicht aus.

1. **Server auswählen.** Es erscheinen nur Server mit einem passenden,
   bearbeitbaren Modul. Der Server-Wechsler bleibt in den weiteren Schritten
   verfügbar; jeder Server hat einen eigenen Entwurf.
2. **Module auswählen.** Angeboten werden ausschließlich geladene, unterstützte
   Module mit deiner Bearbeiten-Berechtigung. Andere geladene Module erreichst
   du über die Links zu ihren vollständigen Einstellungen.
3. **Rollen und Kanäle einstellen.** Rollen und Kanäle lassen sich nach Namen
   auswählen; die ID unterscheidet gleiche Namen. Weitere Einstellungen sind
   eingeklappt. Fehler behalten deinen eingegebenen Text und deine Auswahl bei.
4. **Änderungen prüfen.** Die Vorschau zeigt bisherigen und neuen Wert, aktive
   Funktionen und die tatsächlich geprüften Bot-Rechte. Erst die Bestätigung
   und **Jetzt übernehmen** speichern. Beim Übernehmen werden Server, Rechte,
   Rollen, Kanäle und die Aktualität der Vorschau erneut geprüft.
5. **Vorschau und Tests.** Öffne die passende Modul-Vorschau beziehungsweise
   prüfe die gespeicherten Einstellungen. Für Begrüßung gibt es zusätzlich
   **Testnachricht senden**: eine echte Nachricht in den angezeigten Kanal,
   mit dir als Beispiel und ohne Erwähnungen. Dieser Test ist eine eigene
   Aktion nach dem Speichern; er setzt eine Servermitgliedschaft voraus.

## Unterstützte Grundlagen

| Modul | Im Assistenten |
|---|---|
| Tickets | Support-Rollen, Ticket-Art und Ziel, optional Protokoll- und Ersteller-Rolle, Ticket-Limit |
| Begrüßung | Aktivierung für zukünftige Beitritte, Kanal, Text, Darstellungsart |
| Automatische Rollen | Aktivierung für zukünftige Beitritte, Beitrittsrollen, Mitgliedschaftsprüfung, Verzögerung |
| Umfragen | Wer erstellen darf, Verwalter-Rollen, Standardregeln und Antwort-Limit |
| RaidHelper | Anmeldekanal, Verwalter-Rollen, Spiel, Zeitzone und Erinnerungs-Vorgabe |
| Organigramm | Neuer unveröffentlichter Entwurf aus ausgewählten Rollen; vorhandene Organigramme bleiben erhalten |
| Sticky | Neue **deaktivierte** Textvorlage in einem bislang nicht belegten Kanal |
| Gewinnspiele | Verwalter-Rollen, Zeitzone und Aufbewahrung |
| Geplante Nachrichten | Standard-Zeitzone; bestehende Termine bleiben erhalten |

Das Speichern veröffentlicht keine Panels, Organigramme oder Nachrichten,
erstellt keine Raids, Umfragen, Gewinnspiele oder Termine und vergibt keine
Rollen an vorhandene Mitglieder. Aktivierte Begrüßung und automatische Rollen
gelten anschließend für zukünftige Beitritte. Bestehende Einstellungen, die der
Assistent nicht anbietet, bleiben erhalten.

## Entwürfe und Fehler

Ein Entwurf ist 30 Minuten in derselben angemeldeten Browsersitzung für denselben
Nutzer und Server fortsetzbar. Er liegt ausschließlich im Arbeitsspeicher; ein
Bot-Neustart verwirft ihn. Eine neue Modulauswahl kann den Entwurf ändern. Eine
neue Prüfung ersetzt die vorherige Freigabe. Abgelaufene oder in eine andere
Sitzung kopierte Bestätigungen werden abgelehnt.

Ändert sich eine betroffene Einstellung nach der Vorschau oder wird ein Modul
neu geladen, musst du erneut prüfen. Unabhängige Änderungen an anderen
Einstellungen bleiben erhalten. Schlägt eine mehrteilige Übernahme fehl oder
wird sie abgebrochen, nimmt der Assistent bereits gespeicherte eigene Änderungen
zurück. Fremde, zwischenzeitliche Änderungen werden dabei nicht überschrieben.
Falls die Rücknahme selbst fehlschlägt, zeigt das Dashboard dies ausdrücklich an
und verweist auf die vollständigen Einstellungen; der Bot protokolliert die
betroffenen Schlüssel.

Automatisch vergebene Rollen werden zusätzlich gegen Bot-Hierarchie,
verwaltete Rollen und deine erlaubte Rollenvergabe geprüft. Reine Verweise wie
Support- oder Organigramm-Rollen vergeben keine Rolle und verwenden daher diese
zusätzliche Vergabeprüfung nicht.

Eine Red-Datenschutzanfrage entfernt die kurzlebigen Entwürfe des betroffenen
Nutzers. Sie enthalten die gewählten Einstellungen und die Nutzerzuordnung,
jedoch keine Sitzungscookies oder Zugangsdaten.
