# Projektmanagement und Kalender (TeamCalendar)

Ein gemeinsamer Kalender für das Projektteam: Treffen, Besprechungen und andere Termine
mit Projekt, Verantwortlichen, Ort, Notizen und Zu-/Absagen. **Alle eingerichteten Teammitglieder
dürfen standardmäßig alle Termine anlegen und verwalten**, auch wenn jemand anderes sie erstellt
hat. Ergänzt werden **Projekte, ein Aufgabenboard, Zuständigkeiten, Checklisten, Kommentare und
Meilensteine**. Discord-Buttons und WebCore-Dashboard verwenden dieselbe Daten- und Rechteprüfung.
Der Cog heißt weiterhin `teamcalendar`; bestehende Termine, Rollen und Kalender-Übersichten bleiben erhalten.

## Installation

```text
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs teamcalendar
[p]load teamcalendar
```

Für die Verwaltung im Browser zusätzlich **WebCore** laden. Ohne WebCore bleibt die Bedienung
über Discord verfügbar. Die Abhängigkeit **tzdata** liefert insbesondere unter Windows die
Zeitzonendaten und wird bei der Cog-Installation mit installiert.

## In wenigen Schritten starten

1. Als Server-/Bot-Owner oder Discord-Administrator `[p]termine setup #teamkalender @Projektteam`
   ausführen. Das richtet die Teamrolle ein und veröffentlicht die Übersicht im gewählten Kanal.
   Alternativ im Dashboard zuerst **Einstellungen → Teamrollen** speichern und dann ausdrücklich
   **Kalender dort veröffentlichen** wählen.
2. Einen **privaten Teamkanal** verwenden: Alle Leser des gewählten Kalender- oder Erinnerungskanals
   können die dort veröffentlichten Termininhalte sehen. Der Cog ändert keine Discord-Kanalrechte.
3. Für die Browserbedienung in **WebCore → Zugriff & Rollen** den Teamrollen bei **Projektmanagement**
   mindestens **Bedienen** geben. Die Kalenderverwaltung benötigt **Bearbeiten**. Die Rollenvergabe
   im Kalender selbst richtet keine WebCore-Rechte automatisch ein.
4. **Termin erstellen** in Discord oder **Termin planen** im Dashboard öffnen. Titel, Beginn und Ende
   eintragen und speichern. Das gesamte berechtigte Team kann ihn anschließend bearbeiten.

Neue Kalender haben noch keine Teamrollen; zunächst dürfen nur Administratoren sowie Server- und
Bot-Owner die Einrichtung öffnen. Zusätzliche **Kalenderverwaltungsrollen** lassen sich dort festlegen.

## Befehle

`[p]` steht für den Bot-Präfix; die Befehle sind auch als Slash-Befehle verfügbar.
`[p]kalender` ist ein Alias für `[p]termine`.

| Projekt-/Aufgabenbefehl | Beschreibung | Rechte |
|---|---|---|
| `[p]projekte liste` | Projekte und ihren Fortschritt anzeigen. | Team |
| `[p]projekte neu` | Projektformular öffnen. | Projektverwaltung |
| `[p]projekte details <nummer>` | Projektdetails mit zugehörigen Aufgaben anzeigen. | Team |
| `[p]projekte status <nummer> <aktiv\|pause\|abgeschlossen\|archiv>` | Projektstatus ändern. | Projektverwaltung |
| `[p]aufgaben liste [nurmeine]` | Gemeinsame oder eigene Aufgaben anzeigen. | Team |
| `[p]aufgaben neu` | Neue Aufgabe anlegen. | Vollständige Aufgabenverwaltung |
| `[p]aufgaben details <nummer>` | Aufgabe, Checkliste und Kommentare öffnen. | Team |
| `[p]aufgaben status <nummer> <offen\|arbeit\|blockiert\|erledigt>` | Aufgabenstatus setzen. | Aufgabenbearbeitung |
| `[p]aufgaben zuweisen <nummer> [mitglied]` | Aufgabe zuweisen; ohne Mitglied freigeben. | Vollständige Aufgabenverwaltung |
| `[p]aufgaben kommentar <nummer> <text>` | Kommentar zur Aufgabe hinzufügen. | Aufgabenbearbeitung |
| `[p]aufgaben board [kanal]` | Aufgabenübersicht aktualisieren oder in einem Kanal veröffentlichen. | Projektverwaltung; Kanalwechsel: Kalenderverwaltung |

Projekt- und Aufgabenlöschung werden über die Details mit Bestätigung angeboten.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]termine liste [tage]` | Anstehende Termine anzeigen, Standard 30 Tage; 1–365 möglich. | Team |
| `[p]termine neu` | Formular zum Anlegen eines Termins öffnen. | Terminverwaltung |
| `[p]termine details <nummer>` | Details und Aktionen zu einem Termin öffnen. | Team |
| `[p]termine teilnahme <nummer> <ja\|vielleicht\|nein\|entfernen>` | Eigene Zu-/Absage setzen oder entfernen. | Team |
| `[p]termine absagen <nummer>` | Termin absagen und im Kalender behalten. | Terminverwaltung |
| `[p]termine erledigt <nummer>` | Termin als erledigt markieren. | Terminverwaltung |
| `[p]termine loeschen <nummer>` | Termin samt Rückmeldungen nach Bestätigung entfernen. | Terminverwaltung |
| `[p]termine setup <kanal> <teamrolle>` | Teamrolle ergänzen und Übersicht ausdrücklich veröffentlichen. | Kalenderverwaltung |
| `[p]termine board [kanal]` | Übersicht aktualisieren; mit Kanal neu veröffentlichen/verschieben. | Terminverwaltung; Kanalwechsel: Kalenderverwaltung |

**Team** bedeutet eine eingerichtete Teamrolle oder Kalenderverwaltung. **Terminverwaltung** umfasst
standardmäßig das ganze Team. Der Schalter **Alle Teammitglieder dürfen Termine verwalten** ist
bereits eingeschaltet. Wird er bewusst ausgeschaltet, kann das Team weiter lesen und Rückmeldungen
geben; Änderungen bleiben der Kalenderverwaltung vorbehalten. Verantwortlichkeit und Erstellerschaft
vergeben keine exklusiven Bearbeitungsrechte. **Server verwalten** allein genügt nicht.

## Bedienung in Discord

Die Übersicht bietet **Termin erstellen**, **Termine ansehen** und **Kalender exportieren**.
Über die Auswahl öffnest du einen Termin mit Zeiten, Ort, Notizen, Verantwortlichem und Rückmeldungen.
Das Team kann zusagen, vielleicht wählen, absagen oder seine Rückmeldung entfernen. Berechtigte
Teammitglieder können zusätzlich bearbeiten, kopieren, absagen, erledigen, wieder einplanen oder löschen.

Die Übersicht zeigt die nächsten Termine; weitere erreichst du über die Termin-Auswahl. Buttons der
Übersicht funktionieren nach einem Bot-Neustart weiter. Details und Bestätigungen werden jeweils
mit den aktuellen Teamrechten geprüft. Inhalte werden ohne Rollen- oder Nutzer-Pings versendet.

## Dashboard

Die bestehende WebCore-Seite unter `/cogs/teamcalendar` bietet sieben Bereiche:

- **Projekte:** neue Projekte anlegen, beschreiben, einer verantwortlichen Person zuordnen und mit
  einer optionalen Frist versehen. Karten zeigen erledigte/gesamte Aufgaben, Fortschritt, Blockaden
  und Meilensteine. „Aufgaben öffnen“ filtert das Board auf dieses Projekt.
- **Aufgabenboard:** vier Spalten **Offen**, **In Arbeit**, **Blockiert**, **Erledigt**. Neue Aufgaben
  erhalten Projekt, bis zu zehn Zuständige, optionale Frist, Priorität, Beschreibung und Checkliste.
  Status über die Auswahl setzen; Drag-and-drop ist nicht erforderlich. Filter: Projekt, Status,
  Zuständiger, Priorität, überfällige Frist und Textsuche. Auf schmalen Bildschirmen stehen die Spalten
  untereinander. Pro Spalte werden höchstens 100 Treffer gezeigt; bei mehr Aufgaben die Filter eingrenzen.
- **Meine Aufgaben:** nur deine eigenen noch nicht erledigten Zuweisungen, unabhängig vom Boardfilter.

- **Agenda:** anstehende Termine oder alle Termine einschließlich Absagen, nach Projekt filterbar.
  Details zeigen Verantwortliche und die Namen der Personen mit Zu-/Absage. Die Agenda zeigt höchstens
  200 passende Termine; Projektfilter, Monatsansicht und Export helfen bei größeren Kalendern.
- **Monat:** Übersicht mit vorigem/nächstem Monat und „Heute“. Mehrtagestermine erscheinen an jedem
  betroffenen Tag. Auf schmalen Bildschirmen wird daraus eine Tagesliste mit den belegten Tagen.
- **Termin planen:** neues Ereignis mit Titel, lokaler Anfangs-/Endzeit, Projekt, Verantwortlichem,
  Ort/Link, Beschreibung und Erinnerungen. Ein bestehender Termin wird über seine Details bearbeitet.
  **Als neuen Termin +7 Tage kopieren** öffnet nur ein vorausgefülltes Formular: lokale Uhrzeiten
  bleiben erhalten, Rückmeldungen werden nicht übernommen. Erst Speichern erstellt den neuen Termin.
- **Einstellungen:** Team- und Kalenderverwaltungsrollen, Teamverwaltungsschalter, Zeitzone,
  Projekt-/Aufgabenrechte, Standard-Erinnerungen, Erinnerungskanal und Aufbewahrung. Die Discord-Übersichten werden über einen
  eigenen Button ausdrücklich veröffentlicht; Ansichten und Export posten nichts.

Fehlerhafte Eingaben bleiben kurzzeitig in der jeweiligen Sitzung erhalten. Entwürfe sind nach
Nutzer, Server und Termin getrennt. Wird ein Termin während der Bearbeitung geändert, verhindert
die Versionsprüfung ein unbeabsichtigtes Überschreiben. **Aktuellen Stand neu laden** öffnet die
gespeicherte Fassung; die neue Änderung lässt sich danach erneut prüfen und speichern.

| WebCore-Stufe | Zusätzlich erforderliche Kalenderrechte | Darf |
|---|---|---|
| Ansehen | Team | Agenda, Monat, Details und ICS-Export lesen |
| Bedienen | Team | Eigene Zu-/Absage verwalten |
| Bedienen | Terminverwaltung | Termine anlegen, auch fremde bearbeiten, kopieren, absagen, erledigen, wieder einplanen und löschen; Übersicht erneut aktualisieren |
| Bearbeiten | Kalenderverwaltung | Einstellungen ändern und Übersicht in einem Kanal veröffentlichen/verschieben |

Beide Rechteprüfungen gelten gleichzeitig. Ein WebCore-Allowlist-Eintrag allein öffnet keinen
fremden Teamkalender. Ohne Kalenderrolle sind auch direkte Termin- und Download-Adressen gesperrt.

## Projekte und Aufgaben im Alltag

Ein guter Einstieg: **Projekte → Neues Projekt**, anschließend **Aufgaben öffnen → Neue Aufgabe**.
Ein Projekt hat eine Beschreibung, eine verantwortliche Person und optional eine Frist. Aufgaben
können auch ohne Projekt existieren. Verantwortliche und Zuständige müssen aktuell zum eingerichteten
Team gehören; Bots sind ausgeschlossen.

Eine Aufgabe enthält Titel, Beschreibung, Zuständige, Frist und **Niedrig/Normal/Hoch/Dringend**.
**Meilenstein** markiert ein wichtiges Ergebnis und braucht sowohl Projekt als auch Frist. Die
Prozentanzeige berechnet sich aus erledigten Aufgaben; Checklistenpunkte zählen nicht als eigene Aufgaben.
Pro Server sind bis zu 100 Projekte und 500 Aufgaben möglich. Projekte sind auf 80 Zeichen im Namen,
Aufgaben auf 100 Zeichen im Titel und beide auf 2000 Zeichen Beschreibung begrenzt.

In den Aufgabendetails stehen Checkliste, Kommentare und Änderungsverlauf. Checklisten haben bis zu
25 Punkte mit jeweils 200 Zeichen. Ein Punkt pro Zeile; beim Umordnen bleiben vorhandene Häkchen
am gleichen Text erhalten. Einzelne Häkchen werden direkt in den Details gesetzt. Kommentare
haben 1–1000 Zeichen; höchstens 50 pro Aufgabe. Verfasser können eigene Kommentare auch nach einer
Neuzuweisung entfernen; die Kalenderverwaltung darf fremde Kommentare löschen. Der Verlauf hält
die letzten 50 Änderungen fest, ohne gelöschte Kommentartexte zu kopieren.

**Aktiv/Pausiert/Abgeschlossen/Archiviert** steuert Projekte. Aufgaben in pausierten oder archivierten
Projekten erhalten keine Fristerinnerungen. Ein Projekt lässt sich erst abschließen, wenn keine offene
Aufgabe verbleibt. Abgeschlossene und archivierte Projekte nehmen keine neu zugeordneten Aufgaben an;
bestehende Aufgaben bleiben zum Fertigstellen erreichbar. Endgültiges Löschen ist nur bei einem
Projekt ohne Aufgaben möglich. **Archivieren** ist die einfache Alternative, wenn die Historie bleiben soll.

### Wer darf was?

Standard **Das ganze Team**: alle eingerichteten Teammitglieder können Projekte und
Aufgaben vollständig verwalten. **WebCore Bedienen** ist zusätzlich für Änderungen im Dashboard nötig.
Einrichten und Veröffentlichen in einem neuen Kanal bleibt der Kalenderverwaltung mit **Bearbeiten** vorbehalten.
Diese Auswahl ist unabhängig vom Schalter für die Terminverwaltung im Kalender.

Optional unter **Einstellungen → Projekt- und Aufgabenverwaltung** den zugewiesenen Modus wählen:

| Aktion | Kalenderverwaltung | Zugewiesenes Teammitglied | Übriges Team |
|---|---|---|---|
| Projekte/Aufgaben lesen, CSV exportieren | Ja | Ja | Ja |
| Projekte verwalten, Aufgaben anlegen/vollständig bearbeiten/zuweisen/löschen | Ja | Nein | Nein |
| Status und Checkliste einer Aufgabe ändern, kommentieren | Ja | Nur eigene Zuweisungen | Nein |
| Eigenen Kommentar entfernen | Ja | Ja | Ja, sofern Verfasser |

Erstellerschaft oder ein fremder Nutzerparameter umgehen diese Rechte nicht. Ein Rollenentzug wird
bei der nächsten Aktion erneut geprüft. Kommentare verändern keinen Formular-Versionsstand; andere
Änderungen werden gegen paralleles Überschreiben geschützt. Fehlerentwürfe sind nach Sitzung,
Person, Server und Projekt/Aufgabe getrennt. Ändert sich inzwischen die Zeitzone, muss die Frist
nach erneutem Laden geprüft werden.

### Kalenderverknüpfung, Fristen und Export

Termine können über **Projekt verknüpfen** einem bestehenden Projekt zugeordnet werden. Sie zeigen
dessen aktuellen Namen; alte freie Projektbezeichnungen bleiben gültig. Eine Aufgabe kann einen
vorhandenen Kalendertermin verlinken. Das Verknüpfen erstellt oder verschiebt keinen Termin, und
eine Aufgabenfrist ist kein automatisch veröffentlichter Discord-Servertermin.

Aufgaben-Erinnerungen lassen sich global einstellen: Standard **1440,60,0** Minuten vor Fälligkeit
(24 Stunden, eine Stunde, bei Fälligkeit); leer schaltet sie aus. Höchstens drei Werte zwischen 0 und
10080 Minuten. Sie erscheinen im Aufgabenkanal, ersatzweise im eingerichteten Erinnerung-/Kalenderkanal,
ohne Rollen- oder Nutzer-Pings. Fehlende Kanäle und pausierte/archivierte Projekte unterdrücken den
Versand. Zuständige finden offene Fristen außerdem im gemeinsamen WebCore-Bereich **Meine Aufgaben**.

**Aufgaben als CSV exportieren** lädt eine angemeldete, teamgeschützte Datei mit Projekt, Status,
Priorität, Zuständigen und Frist. Sie ist für Excel als UTF-8 mit Semikolon vorbereitet, schützt
Textanfänge vor Tabellenformeln und enthält keine Kommentare oder internen Versanddaten. Der Export
ist kein öffentlicher Link und ändert keine Aufgaben.

## Zeiten und Erinnerungen

Standard ist **Europe/Berlin**; die Zeitzone lässt sich pro Server ändern. Eingaben werden als lokale
Zeit interpretiert und als UTC-Zeitpunkt gespeichert. Eine Änderung der Kalender-Zeitzone verschiebt
bestehende Termine nicht. Nicht existierende oder doppelte Uhrzeiten bei einer Zeitumstellung werden
abgelehnt, statt stillschweigend eine Stunde zu raten. In Discord sind außerdem Zeitangaben in der
lokalen Zeitzone der jeweiligen Person sichtbar.

Ein Termin dauert höchstens sieben Tage, neue Anfangszeiten müssen in der Zukunft liegen.
Datumswerte zwischen 2000 und 2100 sind möglich. Titel: 100 Zeichen, Beschreibung: 2000, Projekt: 80,
Ort/Link: 200. Je Server sind höchstens 250 gespeicherte Termine vorgesehen; automatische Wiederholungen
sind nicht enthalten. Für regelmäßige Treffen gibt es die bewusst gespeicherte Kopie eine Woche später.

Voreingestellt sind Erinnerungen **24 Stunden und eine Stunde vorher**. Pro Termin sind keine oder
bis zu drei Erinnerungen zwischen einer Minute und sieben Tagen vorher möglich. Sie erscheinen im
Erinnerungskanal, ansonsten im veröffentlichten Kalenderkanal, jeweils ohne Ping. Ohne eingerichteten
Kanal erfolgt kein Versand. Die Prüfung läuft ungefähr einmal pro Minute. Nach längeren Bot-Ausfällen
werden verpasste alte Erinnerungen nicht gesammelt nachgesendet; das Versandfenster beträgt fünf Minuten.
Bei Fehlern gibt es begrenzte Wiederholungsversuche. Absagen und erledigte Termine werden nicht erinnert.

Bereits veröffentlichte Übersichten werden bei Änderungen aktualisiert. Fehler bleiben mit Hinweis
und Wiederholungsaktion sichtbar. Fehlende Nachrichten werden ersetzt; Rechte- oder Discord-Fehler
sollen keine zweite Übersicht erzeugen. Beim Kanalwechsel wird die alte Übersicht erst nach erfolgreicher
Veröffentlichung der neuen entfernt; eine fehlgeschlagene Entfernung wird gemeldet.

## ICS-Export

**Kalender exportieren (.ics)** lädt eine Datei für den eigenen Kalenderclient herunter. Der Export
ist nur nach Anmeldung und mit Teamzugriff erreichbar, auch in Discord. Er enthält Termine, Zeiten,
Projekte, Ort, Beschreibung und Absagestatus; Teilnehmer-IDs werden nicht als Kalendergäste exportiert.
Es handelt sich um einen Dateiexport, keinen öffentlichen Abonnement-Link. Nach Änderungen erneut
exportieren/importieren; bereits heruntergeladene Dateien bleiben bei der herunterladenden Person.

## Daten und Löschung

Der Cog speichert Termininhalte, UTC-Zeiten, Status, Verantwortliche, Ersteller/letzte Bearbeitung,
Zu-/Absagen, Versionsstand und Erinnerungsmarkierungen sowie die Einrichtung des Kalenders.
Vergangene **abgesagte oder erledigte** Termine werden nach der eingestellten Frist entfernt
(Standard 180 Tage). Vergangene, weiterhin geplante Termine bleiben bis zur Erledigung/Absage oder
manuellen Löschung erhalten.

Zusätzlich bleiben Projekte, Aufgaben, Zuweisungen, Fristen, Checklisten, Kommentare und der begrenzte
Änderungsverlauf gespeichert, bis das Team sie löscht. Die Aufbewahrungsfrist für Kalendertermine
löscht diese Projektdaten nicht automatisch. Red-Datenlöschanfragen entfernen persönliche Zuweisungen
und Autoren-/Bearbeiterbezüge sowie eigene Kommentare und Entwürfe; die gemeinsamen Projekte und
Aufgaben bleiben bestehen. Freie Beschreibungen und Checklisten können weiterhin persönliche Angaben enthalten.

Eine Red-Datenlöschanfrage entfernt die Zu-/Absagen der betreffenden Person und ihre IDs als
Verantwortlicher, Ersteller oder Bearbeiter; ihre kurzlebigen Dashboard-Entwürfe werden verworfen.
Der gemeinsame Termin bleibt bestehen. Freie Texte können weiterhin Namen oder andere persönliche
Angaben enthalten und müssen bei Bedarf vom Team angepasst werden. Nachrichten und heruntergeladene
Dateien liegen zusätzlich bei Discord bzw. den jeweiligen Empfängern.
