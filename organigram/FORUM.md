# Organigram

Postet **Server-Organigramme** nach Discord – als Bild, Embed oder Text. Beliebig viele
benannte Organigramme pro Server, komplett über das Web-Dashboard konfigurierbar.

**Highlights**
- Positionen aus Discord-**Rollen** (Mitglieder automatisch) **und** manuellen Namen.
- Mitglieder wahlweise **mehrfach** in allen passenden Positionen oder **einmal** in ihrer höchsten Position.
- **Drei Modi, pro Post wählbar:** Bild · Embed · Text.
- **Acht Bild-Muster:** Baum, Abteilungen, Pyramide, Kompaktliste, Karten, horizontaler Baum,
  Teamzeilen und Rollenmatrix – mit Avataren
  und Rollenfarben im Dashboard-Look.
- **Automatische Aktualisierung** bei Rollen-/Mitgliederänderungen.
  Bei fehlenden Rechten oder vorübergehenden Discord-Fehlern bleibt die bestehende Post-Zuordnung erhalten.
- **Live-Vorschau** und **PNG-Export** im Dashboard.
- **Schnellstart aus ausgewählten Rollen**, bearbeitbarer Strukturbaum mit Unterposition-/Sortierbuttons.
- **Layout-Beispielgalerie**, Status je Veröffentlichung mit Discord-Link, letztem Erfolg, Fehler und Wiederholen.
- Optional **mehrseitige vollständige Bildausgabe** mit Hierarchieübersicht, Abteilungs-/Personenseiten,
  Seitenauswahl und ZIP-Download; keine Sieben-Personen-Kürzung.

## Installation
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs organigram
[p]load organigram
```

## Befehle
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]organigram list` | Listet alle Organigramme des Servers. | alle |
| `[p]organigram show <name> [modus]` | Zeigt ein Organigramm einmalig an (ohne Auto-Update). | Admin / „Server verwalten“ |
| `[p]organigram post <name> [modus] [#kanal]` | Postet ein Organigramm und hält es automatisch aktuell. | Admin / „Server verwalten“ |
| `[p]organigram refresh <name>` | Aktualisiert alle geposteten Beiträge sofort. | Admin / „Server verwalten“ |
| `[p]organigram stop <name> [#kanal]` | Beendet die Auto-Aktualisierung (Nachricht bleibt). | Admin / „Server verwalten“ |
| `[p]organigram members <name> <multiple\|highest>` | Mitglieder mehrfach oder nur in höchster Position anzeigen. | Admin / „Server verwalten“ |

`modus` = `bild` · `embed` · `text` (optional; sonst Standard des Organigramms). Alias: `org`.

## Dashboard
**Löschen ohne Suchen:** **Organigramm löschen** steht in der Übersicht und oben im geöffneten
Editor. **Position löschen** ist direkt in der Teamstruktur und beim Bearbeiten erreichbar.
Beides erfordert **Bearbeiten** und eine Bestätigung. Unterpositionen rücken beim Entfernen einer
Position eine Ebene hoch; Discord-Rollen und Mitglieder bleiben erhalten. Bereits gepostete
Discord-Nachrichten bleiben beim Entfernen eines Organigramms bestehen.

Ist `webcore` geladen, erscheint automatisch der Tab **Organigramm**: Organigramme anlegen,
Muster/Modus/Farbe wählen, Positionen pflegen (Rolle + manuelle Namen, übergeordnete Position,
Emoji, Farbe, Reihenfolge), Live-Vorschau ansehen, PNG herunterladen und in einen Kanal posten.

**Einfach starten:** Name und Rollen im **Schnellstart** auswählen, Hierarchie oder gleichrangige
Teamübersicht erzeugen und die Vorschau prüfen. Dabei wird nur ein Entwurf angelegt. Erst **Posten**
unter **Vorschau & Posten** veröffentlicht in den gewählten Kanal. **Unterposition** und Pfeile im Baum
helfen beim Aufbau; zusätzliche Felder stehen unter **Weitere Optionen**.

**Neue Layouts:** Der horizontale Baum zeigt Hierarchiestufen von links nach rechts. Teamzeilen bündeln
je Position die Namen in einer breiten Zeile ohne Avatare. Die Rollenmatrix zeigt Personen als Zeilen,
Positionen als Spalten und ihre Zuordnungen als Punkte. **Layout-Beispiele** vergleicht alle acht Muster.

**Sicher aktuell:** Veröffentlichte Beiträge zeigen ihren letzten erfolgreichen Stand, Fehler und Discord-Link.
Ab **Bedienen** lassen sie sich erneut versuchen. Beim Start holt der Bot einen Abgleich nach;
Namen-/Avataränderungen werden ebenfalls berücksichtigt, auch für Bots. Der Schalter **Hinweis „unbesetzt“**
steuert den Leerstandstext; die Position selbst bleibt Teil der Struktur.

**Viele Mitglieder:** Unter **Einstellungen → Große Organigramme: Bildseiten** von **Einzelbild**
(bisheriger Standard mit acht Layouts) auf **Mehrseitig** wechseln. Erst erscheint die Hierarchieübersicht,
danach jede Position mit vollständigen Personenlisten in stabiler Reihenfolge. Zwischen 5 und 50 Personen
bzw. Positionen je Seite einstellbar; **Mehrfach / höchste Position** bleibt wirksam. Die Vorschau bietet
eine Seitenauswahl und **Alle Seiten als ZIP**. Erst **Posten** veröffentlicht, mit einer verfolgten Nachricht
je Bildseite. Wiederholen verwendet dieselben IDs; alte Seiten werden erst nach erfolgreichem Ersatz
entfernt. Fehler bewahren alle bereits gesendeten IDs. Unveränderte automatische Seiten werden übersprungen.
Grenzen: Dateilimit des Servers, 64 MiB je Export und höchstens 500 Seiten; bei Überschreitung klare Meldung
statt gekürzter Mitgliederlisten. Text und Embed behalten ihre bisherigen Einzelbeitrags-Limits.
Gelöschte verfolgte Seiten werden über einzelne oder gesammelte Löschereignisse gezielt repariert;
beim Start prüft ein einmaliger Abgleich in 20er-Gruppen auch offline gelöschte Seiten.

Unter **Einstellungen → Mitglieder** wählst du **Mehrfach** (Standard) oder **Einmal – nur in der
höchsten Position**. Höchste = oberste passende Ebene im Organigramm, unabhängig von der
Discord-Rollenhöhe. Bei gleicher Ebene entscheidet die sichtbare Reihenfolge der Zweige und
Positionen (Reihenfolge, danach Bezeichnung). Zusätzliche Freitext-Namen bleiben unverändert.
Die Auswahl gilt für Bild, Embed, Text und Vorschau. Bei aktiviertem Auto-Update werden bestehende
Posts nachgezogen. Alternativ: `[p]organigram members Team highest` / `multiple`.

## Hinweise
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Dashboard benötigt den geladenen Cog `webcore`.
- Emojis erscheinen nur im **Embed**- und **Text**-Modus (im Bild dient die Farbe als Markierung).
