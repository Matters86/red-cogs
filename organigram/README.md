# Organigram

Postet **Server-Organigramme** nach Discord – als Bild, Embed oder Text. Beliebig
viele benannte Organigramme pro Server, jeweils vollständig über das
**WebCore-Dashboard** konfigurierbar.

- **Hybrid-Datenquelle:** Positionen werden mit Discord-**Rollen** verknüpft
  (Mitglieder erscheinen automatisch) und/oder mit **manuell** eingetragenen Namen
  ergänzt.
- **Mitglieder mehrfach oder einmal anzeigen:** Pro Organigramm wählbar, ob ein
  Mitglied in jeder passenden Position oder nur in seiner höchsten Position steht.
- **Drei Ausgabemodi, pro Post wählbar:**
  - **Bild** – ein gerendertes PNG in einem von acht Mustern, im Dashboard-Look
    (dunkel, Akzentfarbe, Avatare, Rollenfarben).
  - **Embed** – strukturierte Felder je Position.
  - **Text** – kompakter Baum im Codeblock.
- **Acht Bild-Muster:** Baum (oben→unten), Abteilungen (Spalten), Pyramide (Ebenen),
  Kompaktliste, Karten, **Baum (links→rechts)**, **Teamzeilen** und **Rollenmatrix**.
- **Automatische Aktualisierung:** Gepostete Beiträge werden bei Rollen- und
  Mitgliederänderungen automatisch neu gerendert (gebündelt, um Spam zu vermeiden).
  Fehlende Rechte oder vorübergehende Discord-Fehler behalten die bestehende Post-Zuordnung;
  ein späterer Aktualisierungsversuch bearbeitet denselben Beitrag.
- **Schnellstart aus Rollen:** Name vergeben, Rollen auswählen, Hierarchie prüfen –
  erst danach gezielt in einen Kanal posten.
- **Baumeditor:** Unterpositionen direkt hinzufügen, Geschwister mit Pfeilen sortieren,
  Personen anzeigen und die gespeicherte Struktur daneben als Bild sehen.
- **Veröffentlichungsstatus:** Discord-Link, letzter erfolgreicher Stand, Fehlermeldung
  und gezielter Wiederholungsversuch für jeden Beitrag.
- **Vollständige Bildseiten:** Optional Hierarchieübersicht plus lesbare Abteilungs-/Personenseiten
  ohne Sieben-Personen-Kürzung, mit Seitenauswahl und ZIP-Export.
- **Live-Vorschau & PNG-Export** direkt im Dashboard.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs organigram
[p]load organigram
```

Beim Installieren wird automatisch **Pillow** als Abhängigkeit eingerichtet. Die für
den Marken-Look genutzten Schriften (Archivo, IBM Plex Sans/Mono) liegen unter
`assets/fonts/` bei; fehlen sie, weicht der Renderer auf System-Schriften aus.

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]organigram list` | Listet alle Organigramme des Servers. | alle |
| `[p]organigram show <name> [modus]` | Zeigt ein Organigramm einmalig hier an (ohne Auto-Aktualisierung). | Admin / Server verwalten |
| `[p]organigram post <name> [modus] [#kanal]` | Postet ein Organigramm und hält es automatisch aktuell. | Admin / Server verwalten |
| `[p]organigram refresh <name>` | Aktualisiert alle geposteten Beiträge sofort. | Admin / Server verwalten |
| `[p]organigram stop <name> [#kanal]` | Beendet die Auto-Aktualisierung (Nachricht bleibt). | Admin / Server verwalten |
| `[p]organigram members <name> <multiple\|highest>` | Mitglieder mehrfach oder nur in höchster Position anzeigen. | Admin / Server verwalten |

`modus` ist optional und einer von `bild`, `embed`, `text`. Ohne Angabe gilt der im
Dashboard gewählte Standard-Modus des Organigramms. Alias für die Befehlsgruppe: `org`.

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Organigramm**. Dort lassen sich:

- Organigramme anlegen, umbenennen und löschen,
- im **Schnellstart** ausgewählte Rollen als Hierarchie oder gleichrangige Teamübersicht übernehmen,
- pro Organigramm Muster (mit Sofort-Vorschau am Dropdown), Standard-Modus,
  Akzentfarbe und Optionen (Avatare, „unbesetzt“, Auto-Update) einstellen,
- Positionen pflegen (Bezeichnung, übergeordnete Position, verknüpfte Rolle,
  zusätzliche Namen, Emoji, Farbe, Reihenfolge),
- die **Mitgliederanzeige** auf „Mehrfach“ oder „Einmal – nur in der höchsten Position“ setzen,
- eine **Live-Vorschau** ansehen und das **PNG herunterladen**,
- alle acht Layouts in einer **Beispielgalerie** vergleichen und direkt auswählen,
- das Organigramm direkt in einen Kanal **posten**.

Die Dashboard-Anbindung steckt in `cog_load`, `cog_unload` und dem
`on_webcore_ready`-Listener (Standard-Muster dieses Repos).

### Schnellstart und einfache Bearbeitung

1. **Schnellstart** öffnen, Namen vergeben und gewünschte Discord-Rollen auswählen.
2. **Hierarchie ansehen** erstellt einen Entwurf. Die höchste ausgewählte Discord-Rolle
   steht an der Spitze, weitere darunter; **Teamübersicht** ordnet sie gleichrangig an.
   Hierarchie und PNG-Vorschau veröffentlichen noch keine Nachricht.
3. Positionen im Baum mit **Unterposition**, **Nach oben** und **Nach unten** anpassen.
   Die Pfeile sortieren innerhalb derselben übergeordneten Position; der Editor erlaubt auch
   einen anderen Elternknoten. Reihenfolge als Zahl, Emoji und Farbe liegen unter **Weitere Optionen**.
4. Unter **Vorschau & Posten** den Kanal und Ausgabemodus auswählen und ausdrücklich **Posten** klicken.

Die Auswahl von Discord-Rollen ändert keine Mitgliedschaften und vergibt keine Rollen.
Die Personenzahlen und aufklappbaren Namen im Baum folgen der gewählten Mitgliederanzeige.
Der Schalter **Hinweis „unbesetzt“ anzeigen** steuert nur diesen Text: Eine leere Position
bleibt als Teil der Teamstruktur sichtbar.

### Layouts vergleichen

Unter **Layout-Beispiele** stehen dieselben Beispieldaten in allen acht Darstellungen bereit.
In einem vorhandenen Organigramm übernimmt **Layout verwenden** das Muster; bei eingeschaltetem
Auto-Update wird ein bereits veröffentlichter Beitrag anschließend angepasst.

| Layout | Gut geeignet für |
|---|---|
| Baum (oben nach unten) | Klassische Hierarchie mit sichtbaren Verbindungslinien |
| Abteilungen (Spalten) | Teams samt Untergruppen nebeneinander |
| Pyramide (Ebenen) | Vergleich gleichrangiger Positionen |
| Kompaktliste | Schmale Textübersicht mit Baumlinien |
| Karten | Personenübersicht mit großen Avataren |
| Baum (links nach rechts) | Mehrere Hierarchiestufen auf einem breiten Bild |
| Teamzeilen | Je Position eine breite Zeile mit Namen; bewusst ohne Avatare |
| Rollenmatrix | Wer gehört zu welchen Positionen? Punkte markieren die Zuordnung |

Die Matrix verbindet Personen über ihre Discord-ID. Verschiedene Mitglieder mit gleichem Namen
bleiben getrennt; Freitext-Namen werden als einzelne Einträge dargestellt. Die Einstellung
**Mehrfach / höchste Position** gilt auch in der Matrix.

### Aktualisierungsstatus und Fehler

Unter **Vorschau & Posten → Veröffentlichte Beiträge** zeigt jeder Beitrag seinen Discord-Link,
die letzte erfolgreiche Aktualisierung (UTC) und gegebenenfalls den letzten Fehler.
**Erneut versuchen** bearbeitet denselben Beitrag, sobald die fehlenden Rechte oder die
vorübergehende Störung behoben sind. Eine tatsächlich gelöschte Nachricht wird ersetzt;
ein bestätigtermaßen gelöschter Kanal wird aus der Zuordnung entfernt. Archivierte Threads
werden vor dieser Entscheidung über Discord aufgelöst.

Beim Bot-Start werden gespeicherte Beiträge mit eingeschaltetem Auto-Update abgeglichen.
Rollen-, Anzeigenamen- und Avataränderungen lösen neue Aktualisierungen aus, auch für Bots.
`[p]organigram refresh <name>` meldet die Anzahl erfolgreicher und fehlgeschlagener Aktualisierungen.

### Große Organigramme vollständig aufteilen

Unter **Einstellungen → Große Organigramme: Bildseiten** wählst du:

- **Einzelbild** bleibt der Standard und nutzt das gewählte der acht Layouts wie bisher.
- **Mehrseitig** erzeugt zuerst eine vollständige Hierarchieübersicht mit Personenanzahlen.
  Danach folgen in stabiler Hierarchiereihenfolge eigene Seiten für jede Position und deren Personen.
  Lange Listen werden automatisch auf weitere Teile verteilt; jede Person und Position bleibt enthalten.

**Personen / Positionen je Seite** lässt sich zwischen **5 und 50** einstellen (Standard **20**).
Die Einstellung **Mehrfach / höchste Position** wird vor der Aufteilung angewendet; gleiche Namen
werden weiterhin anhand ihrer Discord-ID getrennt. Manuelle Namen bleiben eigene Einträge.
Namen und Positionspfade werden auf den Seiten umbrochen. Die acht gestalteten Übersichtslayouts
bleiben für **Einzelbild** verfügbar; vollständige Bildseiten verwenden ein eigenes lesbares Seitenlayout.

Unter **Vorschau & Posten** kannst du jede Seite einzeln auswählen. **Alle Seiten als ZIP** lädt
sämtliche PNGs mit sicheren, nummerierten Dateinamen herunter. Ein Seitenparameter an einem
PNG-Download lädt stattdessen nur diese Seite. Vorschau und Download veröffentlichen nichts.
`[p]organigram show <name> bild` liefert im Seitenmodus ein ZIP, soweit es in das Discord-Dateilimit
passt; größere Archive lassen sich im Dashboard herunterladen.

**Posten im Bildmodus** veröffentlicht eine Discord-Nachricht je Seite. Alle Nachrichten-IDs
werden verfolgt; Wiederholen und spätere Änderungen bearbeiten bestehende Seiten. Neue IDs
werden sofort gesichert, auch wenn eine spätere Seite scheitert. Überzählige alte Seiten werden
erst entfernt, nachdem alle Ersatzseiten erfolgreich geschrieben wurden. Fehlen Löschrechte,
bleiben die alten IDs für den nächsten Wiederholungsversuch erhalten. Ein Wechsel zurück zu
Einzelbild, Text oder Embed räumt alte Seiten nach demselben Verfahren auf.

Unveränderte automatische Seiten werden anhand ihres Inhalts übersprungen. Ereignisse während
eines laufenden Updates werden zu einem Folgeabgleich zusammengefasst. Veröffentlichungen laufen
in begrenzten Gruppen und mit höchstens einer PNG-Datei je Discord-Nachricht. Pro Seite gilt das
Dateilimit des Servers; ein Export ist auf **64 MiB** und ein Organigramm auf **500 Seiten** begrenzt.
Wenn eine Grenze überschritten wird, erscheint ein Fehler, bevor Bildseiten geändert werden;
es werden keine Mitglieder stillschweigend weggelassen. Dann Seitengröße erhöhen oder das Team
in mehrere Organigramme aufteilen.

Wird eine verfolgte Seite in Discord gelöscht, repariert ein Löschereignis gezielt diese Seite.
Nach einer Bot-Auszeit werden die gespeicherten Seiten einmal in Gruppen von höchstens 20 IDs
geprüft, damit auch offline gelöschte Nachrichten ersetzt werden. Fehlende Leserechte gelten dabei
nicht als Löschung. Normale, unveränderte Aktualisierungen benötigen weiterhin keinen Nachrichtenabruf.

**Embed und Text** bleiben Einzelbeiträge mit ihren bisherigen Discord-Limits und Kürzungshinweisen.
Wer alle Personen als Bilder sehen möchte, wählt **Mehrseitig** und **Bild**.

### Mitglieder nur einmal anzeigen

Unter **Einstellungen → Mitglieder → Mehrere Positionen pro Mitglied** gilt standardmäßig
**Mehrfach**: Wer mehrere verknüpfte Rollen hat, steht in allen passenden Positionen.
**Einmal – nur in der höchsten Position** zeigt jede Discord-ID nur einmal. „Höchste“ bedeutet
die oberste passende Ebene **im Organigramm**, unabhängig von der Höhe der Discord-Rolle.
Bei gleicher Ebene entscheidet die sichtbare Reihenfolge der Zweige und Positionen
(Feld **Reihenfolge**, danach Bezeichnung; bei Gleichstand die bestehende Reihenfolge).

Beispiel: Ein Mitglied hat die Rollen „Leitung“ und „Support“. Steht Leitung über Support,
erscheint es mit **Einmal** nur unter Leitung. Andere Support-Mitglieder bleiben sichtbar.
Zusätzliche Namen aus Freitext bleiben unverändert, auch wenn ein Name einem Discord-Mitglied
gleicht. Verschiedene Discord-Mitglieder mit gleichem Anzeigenamen bleiben getrennte Personen.
Die Einstellung gilt einheitlich für Bild, Embed, Text, Vorschau und die Personenzahlen im Dashboard.
Gepostete Beiträge ziehen die Änderung bei eingeschaltetem Auto-Update automatisch nach.

Per Befehl: `[p]organigram members Team highest` aktiviert die einmalige Anzeige,
`[p]organigram members Team multiple` erlaubt wieder mehrere Positionen.

### Rechte im Dashboard

| Stufe | Darf |
|---|---|
| Ansehen | alles sehen (Organigramme, Positionen, einzelne Seiten, PNG-/ZIP-Download), nichts ändern |
| **Bedienen** | Tagesgeschäft: ein Organigramm in einen Kanal **posten bzw. aktualisieren**, fehlgeschlagene Beiträge erneut versuchen |
| Bearbeiten | zusätzlich Organigramme anlegen/umbenennen/löschen, Einstellungen (Muster, Modus, Farbe, Optionen) und **Positionen** (inkl. verknüpfter Rollen) |

Die Stufen vergibt der Bot-Owner unter *Verwaltung → Zugriff & Rollen* (je Server und Rolle); der Bot-Owner selbst darf immer alles.

## Datenhaltung

Gespeichert werden pro Server nur die Organigramm-Definitionen (Bezeichnungen,
Rollen-IDs, manuelle Namen, Farben, Reihenfolge, Seitenmodus und Seitengröße) sowie Kanal- und alle Nachrichten-IDs der
geposteten Beiträge, Inhaltsprüfsummen je Bildseite, Aktualisierungszeitpunkte und die letzte Fehlermeldung je Beitrag. Mitgliedernamen und Avatare werden ausschließlich zur Anzeige
live abgerufen und **nicht** dauerhaft gespeichert.

## Hinweise

- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.
- Im **Bild**-Modus werden Emojis nicht dargestellt (die Schriften enthalten keine
  Emoji-Glyphen) – nutze dafür den **Embed**- oder **Text**-Modus. Die farbige
  Markierung je Position übernimmt im Bild die Rollen-/Eigenfarbe.
- Je Position werden im **Einzelbild** bis zu sieben Personen gezeigt, der Rest als
  „+N weitere“. **Mehrseitige Bildausgabe** zeigt alle Personen.
- Sehr große Organigramme (Bild über ca. 24 Megapixel bzw. 12 000 px an einer Seite) werden
  nicht als Bild gerendert – das bräuchte mehrere GB Arbeitsspeicher. Posten meldet dann
  „zu groß für ein Bild“, die Dashboard-Vorschau zeigt einen Hinweis; nutze **Embed**/**Text**
  oder ein kompakteres Muster (z. B. „Abteilungen“). Große Bilder werden außerdem ohne
  Kantenglättung (Supersampling) gerendert, um Speicher zu sparen.
