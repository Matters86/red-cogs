# Live-Test mit echtem Bot – Checkliste

Ziel: einmal alles mit echtem Discord durchklicken, bevor die Community es benutzt.
Am besten auf einem **Test-Server** (Level, Gewinnspiele und automatische Verwarn-Maßnahmen wirken sofort
auf echte Mitglieder).

## 0. Vorbereitung
- [ ] `git push origin main`, auf dem Bot `[p]cog update`, danach
  `[p]load serverstats levels giveaways scheduler twitchlive welcome warns` und
  `[p]reload webcore tickets raidhelper poll autorole changelog guard autoroom organigram sticky onlyimagevideo commands fivemadmin`.
- [ ] Reds eingebauten Verwarn-Cog entladen: `[p]unload warnings`.
- [ ] Discord-Developer-Portal → Bot → **Server Members Intent** ist an.
- [ ] Dashboard öffnen → **Verwaltung → Bot-Status**: alle Cogs geladen, Latenz plausibel.
- [ ] **Verwaltung → Fehlerprotokoll** offen lassen und nach jedem Abschnitt kurz prüfen (erwartet: keine `ERROR`).
- [ ] Testkanäle: `#bot-test` (normale Rechte) und `#gesperrt` (dem Bot „Nachrichten senden“ entzogen).
- [ ] **Verwaltung → Sichern & Wiederherstellen**: vor dem Test einmal **Export** herunterladen (Sicherung).

## 1. Raidplaner – alte Events aufräumen
- [ ] Reiter **Einstellungen** → Karte „Aufräumen“: Feld zeigt **30 Tage**. Auf `abc`/`-1` ändern → Speichern → roter Toast „… zwischen 0 und 3650 Tagen …“.
- [ ] Vorher im Reiter **Events** notieren, welche Events älter als 30 Tage sind (Altbestand). Nach dem Laden (spätestens nach ~1 Min., danach stündlich) bzw. sofort nach „Speichern“ sind genau diese weg – Toast „Gespeichert – N alte Events gelöscht“. Die **Discord-Nachrichten bleiben stehen**.
- [ ] Ohne Altbestand: `[p]raid create <heute> <in 2 Min.> Test-Alt` anlegen, Termin verstreichen lassen (der Bot schließt es innerhalb 1 Min. ab), am **nächsten Tag** `[p]raidset cleanup 1` → Antwort „… nach 1 Tagen gelöscht … Jetzt entfernt: 1“.
- [ ] `[p]raidset cleanup 0` → „ist aus“; `[p]raidset cleanup 99999` → Fehlermeldung „0 bis 3650“.
- [ ] Auf der alten Nachricht Klasse wählen / Status-Button / „Abmelden“ klicken → jeweils nur für dich sichtbar: „Dieses Event existiert nicht mehr.“ (kein „Interaktion fehlgeschlagen“).
- [ ] Wiederholung: `[p]raid recurrence <id> daily` auf einem Event in wenigen Minuten → nach dem Termin erscheint der Folgetermin (neue Nachricht); das **neueste** Event der Serie wird nie gelöscht.
- [ ] `[p]raidset settings` zeigt „Alte Events löschen nach: 30 Tagen“. Einstellung zurück auf 30.

## 2. Guard – Honeypot-Warntext
- [ ] **Altbestand**: Bestehender Honeypot-Kanal (vor dem Update angelegt). Reiter **Honeypot** → „Warntext“ ändern → Speichern → Toast „Gespeichert – Warnnachricht im Honeypot-Kanal aktualisiert“. Im Kanal ist die **vorhandene** Bot-Nachricht bearbeitet (keine neue). Kanalthema ändert sich nur, wenn es vorher der alte Warntext war.
- [ ] Erneut speichern ohne Textänderung → kein Edit in Discord.
- [ ] Bot-Nachricht im Honeypot-Kanal von Hand löschen → Text ändern → „neu gepostet“; nächste Änderung editiert diese neue Nachricht.
- [ ] Dem Bot im Honeypot-Kanal „Nachrichten senden“ **und** „Nachrichtenverlauf lesen“ entziehen → Text ändern → roter Toast „Gespeichert, aber … fehlen dort Rechte …“; der Text ist trotzdem gespeichert. Rechte zurückgeben.
- [ ] `[p]guardset honeypot warning Bitte nicht schreiben!` → Antwort „aktualisiert“; `[p]guardset honeypot warning reset` → Standardtext steht wieder im Kanal; `[p]guardset honeypot warning` (ohne Text) gleicht nur ab.
- [ ] `[p]guardset honeypot create testfalle` → neuer Kanal mit Warnnachricht; danach Text im Dashboard ändern → genau diese Nachricht wird bearbeitet. Kanal danach löschen.
- [ ] `[p]guardset language en` (ohne eigenen Text) → Warnnachricht wechselt auf Englisch; zurück auf `de`.
- [ ] Wichtig: Im Honeypot-Kanal selbst **nichts schreiben** (du wirst sonst bestraft, außer du bist ausgenommen).

## 3. Autovoiceroom – Bitrate bei neuer Quelle
- [ ] Reiter **Quellen** → „Neue Quelle“ zeigt das Feld **Bitrate (kbps)**. Mit `64` anlegen → in der Quelle steht 64; einen Raum betreten → neuer Raum hat 64 kbps.
- [ ] Mit `999` anlegen → wird auf das Server-Maximum begrenzt (Hilfetext nennt es). Leer lassen → Server-Standard.

## 4. Posten aus dem Dashboard
- [ ] **Tickets**: Panel anlegen (Buttons) in `#bot-test` → Panel erscheint. Panel bearbeiten → Nachricht wird editiert (keine zweite). Kanal wechseln → alte Nachricht weg, neue im neuen Kanal. Dropdown-Panel mit Grund `Test | abc` → Panel erscheint trotzdem (ohne Emoji). Panel in `#gesperrt` → roter Toast „Posten fehlgeschlagen“.
- [ ] **Umfragen**: Reiter „Neue Umfrage“ → Frage + 3 Optionen + Dauer `10m` → Umfrage in Discord, abstimmen klappt. Dauer `bald` → roter Toast „Dauer nicht erkannt“. Umfrage schließen/löschen → Nachricht editiert/gelöscht.
- [ ] **Raidplaner**: Event schließen/öffnen/löschen im Reiter „Events“ → Discord-Nachricht folgt.
- [ ] **Sticky**: Sticky anlegen (Text) → erscheint unten im Kanal; Text ändern → alte weg, neue da; Webhook-Modus mit Name → postet als Webhook. Text >2000 Zeichen → roter Toast + Hinweis im Editor, nichts gelöscht.
- [ ] **Changelog**: `/changelog` mit langem Titel (≈200 Zeichen) **und** eigener Titel-Vorlage im Reiter „Texte“ → wird gepostet (Titel ggf. mit „…“ gekürzt). Eintrag im Dashboard löschen → Nachricht weg.
- [ ] **Autorole**: Panel anlegen, Kanal `#bot-test`, zwei Rollen (eine mit Emoji ⭐, eine mit Emoji-Text `abc`) → „Posten“ → Panel erscheint ohne Emojis + Toast „Discord hat ein Emoji abgelehnt …“. Emoji korrigieren → Panel wird editiert (kein zweites). Kanal im Panel ändern + speichern → altes Panel verschwindet, neues im neuen Kanal. Panel in `#gesperrt` posten → roter Toast.
- [ ] **Organigramm**: Organigramm anlegen, 2–3 Positionen → Reiter „Vorschau & Posten“: Vorschaubild lädt. Posten als Bild/Embed/Text → je eine Nachricht, erneutes Posten im selben Kanal editiert. Titel mit 300 Zeichen + Embed-Modus → wird gepostet. Sehr großes Organigramm (viele Positionen) im Bild-Modus → Meldung „zu groß für ein Bild …“, Vorschau zeigt Hinweisbild, Bot bleibt reaktionsschnell.

## 6. Mitglieder-Bereich („Mein Bereich“)
- [ ] **Zugriff & Rollen** → Karte „Mitglieder-Bereich“ einschalten (oder `[p]webcore portal on`).
- [ ] Mit einem **Zweit-Account ohne Team-Rolle** `…/me` öffnen → Discord-Login → nur „Mein Bereich“ sichtbar;
  `…/cogs/tickets` und `…/access` liefern „Kein Zugriff“.
- [ ] **Raids:** kommendes Event sichtbar, anmelden mit Klasse/Spec → Discord-Nachricht zeigt die Anmeldung;
  Status „Spät“, dann abmelden → Nachricht aktualisiert sich. Event in einem Kanal, den der Account nicht sieht → erscheint nicht.
- [ ] **Umfragen:** abstimmen, Stimme ändern, zurückziehen → Balken/Zähler in Discord folgen.
- [ ] **Rollen:** Rolle aus einem Panel an-/abwählen → Rolle in Discord gesetzt/entfernt.
- [ ] **Meine Tickets:** Ticket über die Website öffnen (mit Fragen) → Kanal entsteht wie per Button; Verlauf zeigt nur eigene Tickets.
- [ ] **Mein Level** und **Gewinnspiele** (siehe 9/10) erscheinen ebenfalls.
- [ ] Im Raidplaner-Dashboard „Im Mitglieder-Bereich anzeigen“ aus → Kachel „Raids“ verschwindet für den Zweit-Account.

## 7. Raidplaner – Events im Dashboard, Neu posten, Launcher-API
- [ ] Reiter **Neues Event** → Event anlegen → Nachricht mit Buttons erscheint; Datum in der Vergangenheit → roter Toast, Eingaben bleiben.
- [ ] Event **bearbeiten** (Titel/Termin) → dieselbe Nachricht wird geändert.
- [ ] Event-Nachricht in Discord von Hand löschen → Tabelle zeigt „Nachricht fehlt“ → **Neu posten** → neue Nachricht, Anmeldungen bleiben.
- [ ] Reiter **Launcher & Website** einschalten → angezeigte URL im Browser öffnen → JSON mit kommenden Events, **ohne** Namen.

## 8. Twitch-Live
- [ ] `[p]twitchset creds <client_id> <client_secret>` (Nachricht wird gelöscht) → Dashboard „Twitch-Live“ zeigt „Verbunden“.
- [ ] `[p]twitch add <dein-login> #bot-test` → `[p]twitch test` postet eine Testmeldung.
- [ ] Kurz live gehen → innerhalb ~1 Min. **genau eine** Meldung mit Vorschaubild und Ping der gewählten Rolle;
  nach dem Stream (+5 Min.) wird sie zu „war live“ umgeschrieben.
- [ ] Reiter **Launcher & Website** einschalten → JSON zeigt `"live": true` während des Streams.

## 9. Level
- [ ] Mit dem Zweit-Account ein paar Nachrichten schreiben (Abstand > 60 s) → `[p]rank` zeigt XP/Rangkarte.
- [ ] `[p]levelset xp give @Zweitaccount 500` → Level-Up-Meldung erscheint (ohne Massen-Ping).
- [ ] Belohnungsrolle für Level 1 im Dashboard anlegen → Rolle wird vergeben; Rolle **über** der Bot-Rolle → Warnhinweis im Dashboard.
- [ ] `[p]leaderboard`, Dashboard-Rangliste und „Mein Level“ im Mitglieder-Bereich stimmen überein.

## 10. Gewinnspiele
- [ ] Dashboard → **Neues Gewinnspiel** (Ende in 3 Min., 1 Gewinner) in `#bot-test` → Nachricht mit Teilnahme-Button.
- [ ] Mit dem Zweit-Account teilnehmen (Button **und** über „Mein Bereich → Gewinnspiele“); erneut klicken → Rückfrage „austreten“.
- [ ] Bot währenddessen einmal neu laden (`[p]reload giveaways`) → Button funktioniert weiter.
- [ ] Nach Ablauf: Gewinner wird angekündigt (nur der Gewinner gepingt), Embed „beendet“; **Neu auslosen** im Dashboard.
- [ ] Gewinnspiel mit benötigter Rolle, die der Zweit-Account nicht hat → Teilnahme abgelehnt.

## 11. Geplante Nachrichten
- [ ] Dashboard → **Neue Nachricht**: „alle 10 Minuten“ in `#bot-test` → „Jetzt testen“ postet sofort (ohne Ping).
- [ ] Nächste Ausführung abwarten → Nachricht kommt pünktlich; „Vorherige Nachricht löschen“ an → alte verschwindet.
- [ ] Eintrag auf `#gesperrt` umstellen → nach 5 Fehlversuchen „automatisch pausiert“ mit rotem Hinweis; Kanal zurück, **Fortsetzen**.
- [ ] `[p]schedule add #bot-test "täglich 09:00" Guten Morgen!` → erscheint in der Liste mit korrekter nächster Zeit (deutsche Zeit).

## 12. Willkommen & Verwarnungen
- [ ] `welcome`: Kanal + Text setzen, Willkommensbild an → `[p]welcomeset test`; Zweit-Account verlässt/betritt den Server → Abschied/Willkommen.
- [ ] `warns`: `[p]warn @Zweitaccount Test` → DM + Log; Schwelle „Timeout ab 2 Punkten“ setzen, zweite Verwarnung → Timeout wird verhängt;
  `[p]unwarn <id>`; Verwarnen eines Mods mit höherer Rolle → abgelehnt.

## 13. Statistik
- [ ] Dashboard „Statistik“: Zeitzone steht auf **Europe/Berlin**; nach ein paar Minuten Aktivität zeigen Nachrichten/Voice-Zahlen
  Werte für **heute** (deutsches Datum). `[p]stats` zeigt dieselben Zahlen. CSV-Export öffnet sich in Excel mit Umlauten korrekt.

## 14. Verwaltung
- [ ] **Audit-Log**: alle Dashboard-Änderungen der Tests stehen drin; `[p]webcore auditchannel #bot-test` → neue Änderungen erscheinen als Embed.
- [ ] **Sichern & Wiederherstellen**: die Datei aus Schritt 0 importieren → Vorschau zeigt Unterschiede (inkl. „Dashboard-Einstellungen“
  nur mit Häkchen) → übernehmen → danach **Rückgängig** → Stand vor dem Import ist wieder da.
- [ ] Mitglied mit Team-Rolle „Ansehen“ öffnet eine Seite → blauer Balken „Nur Ansicht“, Speichern nicht möglich.

## Nachher
- Fehlerprotokoll im Dashboard und Bot-Log auf `ERROR`/Tracebacks prüfen (erwartet: höchstens Warnungen wie
  „Discord lehnt die Komponenten ab … ohne Emojis erneut“).
- Auf dem Test-Server gewonnene Einstellungen per Export sichern.
