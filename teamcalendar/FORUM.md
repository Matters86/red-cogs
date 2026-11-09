# 📋 Projektmanagement und Kalender (TeamCalendar)

Ein gemeinsamer Kalender für dein Projektteam: Termine, Projekte, Verantwortliche, Notizen,
Zu-/Absagen, Erinnerungen und ICS-Export. **Alle eingerichteten Teammitglieder dürfen standardmäßig
auch fremde Termine verwalten.** Dazu kommen Projekte, Aufgabenboard, Zuständigkeiten, Checklisten,
Kommentare und Meilensteine. Bedienung über Discord und das WebCore-Dashboard. Der Cog heißt weiterhin
`teamcalendar`; vorhandene Kalenderdaten bleiben bestehen.

**Installation**

```text
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs teamcalendar
[p]load teamcalendar
```

**Schnellstart:** `[p]termine setup #teamkalender @Projektteam` als Server-/Bot-Owner oder
Discord-Administrator ausführen. Dadurch wird die Teamrolle eingerichtet und die Übersicht
ausdrücklich gepostet. Einen **privaten Teamkanal** wählen: Alle Kanal-Leser sehen veröffentlichte
Termininhalte. Discord-Kanalrechte werden nicht automatisch geändert.

Für die Browserbedienung zusätzlich in **WebCore → Zugriff & Rollen** den Teamrollen mindestens
**Bedienen** für **Projektmanagement** geben; Einrichtung benötigt **Bearbeiten** und Kalenderverwaltung.
Ohne eingerichtete Teamrolle ist der Kalender zunächst nur für Administratoren und Server-/Bot-Owner offen.

**Funktionen**

- Projekte mit Fortschritt, Meilensteinen und Verantwortlichen
- Aufgabenboard: Offen, In Arbeit, Blockiert, Erledigt; eigene Aufgaben und Filter
- Mehrere Zuständige, Priorität, Frist, Checklisten, Kommentare und Änderungsverlauf
- Wahlweise ganzes Team oder Verwaltung plus Zuständige bearbeiten Aufgaben
- Aufgaben mit Kalenderterminen verknüpfen; geschützter CSV-Export für Excel
- Agenda mit Projektfilter und Monatsübersicht; mobile Ansicht als Tagesliste
- Titel, Beschreibung, Projekt, Ort/Link, Verantwortliche und lokale Anfangs-/Endzeit
- Alle Teammitglieder verwalten standardmäßig alle Termine; auf Kalenderverwaltung einschränkbar
- Zusagen, Vielleicht und Absagen; Bearbeiten, Kopieren +7 Tage, Absagen, Erledigen, Wiederplanen, Löschen
- Erinnerungen im Teamkanal, standardmäßig 24 Stunden und eine Stunde vorher, ohne Nutzer-/Rollen-Pings
- Discord-Übersicht mit dauerhaften Buttons und ausdrücklicher Veröffentlichung
- Anmeldungsgeschützter ICS-Dateiexport, ohne öffentliche Kalenderadresse
- Versionsschutz bei gleichzeitiger Bearbeitung; fehlerhafte Dashboard-Eingaben bleiben kurzzeitig erhalten

**Befehle**

`[p]` ist dein Bot-Präfix; auch als Slash-Befehle verfügbar. `[p]kalender` ist ein Alias.

| Projekt-/Aufgabenbefehl | Beschreibung | Rechte |
|---|---|---|
| `[p]projekte liste` | Projekte und Fortschritt anzeigen. | Team |
| `[p]projekte neu` | Projektformular öffnen. | Projektverwaltung |
| `[p]projekte details <nummer>` | Projekt und Aufgaben öffnen. | Team |
| `[p]projekte status <nummer> <aktiv\|pause\|abgeschlossen\|archiv>` | Projektstatus ändern. | Projektverwaltung |
| `[p]aufgaben liste [nurmeine]` | Gemeinsame oder eigene Aufgaben anzeigen. | Team |
| `[p]aufgaben neu` | Neue Aufgabe anlegen. | Vollständige Aufgabenverwaltung |
| `[p]aufgaben details <nummer>` | Aufgabe, Checkliste und Kommentare öffnen. | Team |
| `[p]aufgaben status <nummer> <offen\|arbeit\|blockiert\|erledigt>` | Aufgabenstatus setzen. | Aufgabenbearbeitung |
| `[p]aufgaben zuweisen <nummer> [mitglied]` | Zuweisen oder ohne Mitglied freigeben. | Vollständige Aufgabenverwaltung |
| `[p]aufgaben kommentar <nummer> <text>` | Kommentieren. | Aufgabenbearbeitung |
| `[p]aufgaben board [kanal]` | Aufgabenübersicht aktualisieren oder veröffentlichen. | Projektverwaltung; Kanalwechsel: Kalenderverwaltung |

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

**Team** meint eingerichtete Teamrollen und Kalenderverwaltung. **Terminverwaltung** umfasst im
Standard das ganze Team, unabhängig davon, wer verantwortlich ist oder den Termin erstellt hat.
**Kalenderverwaltung**: eingerichtete Verwaltungsrollen, Discord-Administrator, Server-Owner und Bot-Owner.
**Server verwalten** oder ein WebCore-Allowlist-Eintrag allein ersetzt keine Kalenderrolle.

**Dashboard:** Agenda · Monat · Termin planen · Einstellungen. Details öffnen für Rückmeldungen
und Änderungen. „Als neuen Termin +7 Tage kopieren“ bereitet eine neue Woche vor und übernimmt keine
Rückmeldungen; erst Speichern erstellt den neuen Termin. Bei paralleler Bearbeitung schützt der
Versionsstand vor versehentlichem Überschreiben. Einstellungen und Kanalveröffentlichung bleiben
der Kalenderverwaltung mit WebCore **Bearbeiten** vorbehalten. Export und Ansichten posten nichts.

**Projektmanagement:** Zusätzlich **Projekte · Aufgabenboard · Meine Aufgaben**. Erst Projekt anlegen,
dann Aufgaben mit bis zu zehn Zuständigen, Priorität und Frist ergänzen. Meilensteine brauchen Projekt
und Frist. Im Aufgabenboard lassen sich Status direkt auswählen und Aufgaben nach Projekt, Status,
Zuständigen, Priorität, Überfälligkeit und Text filtern. Details enthalten bis zu 25 Checklistenpunkte,
50 Kommentare und die letzten 50 Änderungen. Kommentare haben höchstens 1000 Zeichen; eigene Kommentare
oder als Verwaltung auch fremde können entfernt werden. Bei paralleler Bearbeitung schützt die Version
vor versehentlichem Überschreiben.

Standardmäßig verwaltet das gesamte berechtigte Team Projekte und Aufgaben, unabhängig vom Schalter
für Kalender-Terminverwaltung. Im optionalen **Zuständigenmodus** erstellt und plant die Kalenderverwaltung;
zugewiesene Mitglieder ändern Status, Checkliste und Kommentare ihrer Aufgaben. Das übrige Team liest mit.
Für Webänderungen ist zusätzlich **Bedienen** erforderlich, für Einrichtung **Bearbeiten**. Kalender- und
Aufgabenübersichten werden nur über den jeweiligen Veröffentlichungsbutton ausdrücklich in einem Teamkanal gepostet.

Projekte lassen sich pausieren, abschließen oder archivieren. Abschluss braucht ausschließlich erledigte
Aufgaben; endgültig gelöscht werden nur leere Projekte. Pausierte/archivierte Projekte erhalten keine
Aufgaben-Fristerinnerungen. Standard für Aufgaben: 24 Stunden, eine Stunde und bei Fälligkeit; global
abschaltbar. Bis zu 100 Projekte und 500 Aufgaben pro Server. Aufgaben-CSV ist ein geschützter,
formelsicherer Dateiexport ohne Kommentare. Alte freie Projektbezeichnungen an Terminen bleiben gültig;
neue Verknüpfungen zeigen den aktuellen Projektnamen. Eine Aufgabenfrist erstellt keinen Kalendertermin.

**Zeiten:** Standard **Europe/Berlin**, pro Server änderbar. Beginn und Ende werden als UTC-Zeitpunkte
gespeichert; Sommerzeit-Lücken und doppelte Uhrzeiten werden nicht geraten. Bis zu 250 Termine pro
Server, jeweils höchstens sieben Tage Dauer. Automatische Wiederholung ist nicht enthalten.
Erinnerungen: keine oder höchstens drei Werte zwischen einer Minute und sieben Tagen vorher.
Die Prüfung läuft ungefähr minütlich; nach langen Ausfällen werden alte Erinnerungen außerhalb des
fünfminütigen Versandfensters nicht gesammelt nachgesendet.

**Export und Daten:** ICS ist ein geschützter Dateidownload, kein öffentlicher Abo-Link. Teilnehmer-IDs
werden nicht als Kalendergäste exportiert. Standardmäßig werden erledigte/abgesagte vergangene Termine
nach 180 Tagen entfernt. Bei Red-Datenlöschanfragen verschwinden die Teilnahme-/Personen-IDs und
Dashboard-Entwürfe der Person; gemeinsame Termininhalte bleiben bestehen. Freie Texte und bereits
heruntergeladene oder in Discord veröffentlichte Inhalte bei Bedarf zusätzlich prüfen.

Projekte und Aufgaben bleiben bis zur manuellen Löschung gespeichert. Datenlöschanfragen entfernen
persönliche Zuweisungen, Personenbezüge, eigene Kommentare und Entwürfe; gemeinsame Aufgaben und freie
Texte werden nicht automatisch gelöscht. Die Termin-Aufbewahrungsfrist gilt nicht für Projektdaten.
