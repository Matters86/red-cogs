# Organigram

Postet **Server-Organigramme** nach Discord – als Bild, Embed oder Text. Beliebig
viele benannte Organigramme pro Server, jeweils vollständig über das
**WebCore-Dashboard** konfigurierbar.

- **Hybrid-Datenquelle:** Positionen werden mit Discord-**Rollen** verknüpft
  (Mitglieder erscheinen automatisch) und/oder mit **manuell** eingetragenen Namen
  ergänzt.
- **Drei Ausgabemodi, pro Post wählbar:**
  - **Bild** – ein gerendertes PNG in einem von fünf Mustern, im Dashboard-Look
    (dunkel, Akzentfarbe, Avatare, Rollenfarben).
  - **Embed** – strukturierte Felder je Position.
  - **Text** – kompakter Baum im Codeblock.
- **Fünf Bild-Muster:** Baum (oben→unten), Abteilungen (Spalten), Pyramide (Ebenen),
  Kompaktliste, Karten.
- **Automatische Aktualisierung:** Gepostete Beiträge werden bei Rollen- und
  Mitgliederänderungen automatisch neu gerendert (gebündelt, um Spam zu vermeiden).
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

`modus` ist optional und einer von `bild`, `embed`, `text`. Ohne Angabe gilt der im
Dashboard gewählte Standard-Modus des Organigramms. Alias für die Befehlsgruppe: `org`.

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Organigramm**. Dort lassen sich:

- Organigramme anlegen, umbenennen und löschen,
- pro Organigramm Muster (mit Sofort-Vorschau am Dropdown), Standard-Modus,
  Akzentfarbe und Optionen (Avatare, „unbesetzt“, Auto-Update) einstellen,
- Positionen pflegen (Bezeichnung, übergeordnete Position, verknüpfte Rolle,
  zusätzliche Namen, Emoji, Farbe, Reihenfolge),
- eine **Live-Vorschau** ansehen und das **PNG herunterladen**,
- das Organigramm direkt in einen Kanal **posten**.

Die Dashboard-Anbindung steckt in `cog_load`, `cog_unload` und dem
`on_webcore_ready`-Listener (Standard-Muster dieses Repos).

## Datenhaltung

Gespeichert werden pro Server nur die Organigramm-Definitionen (Bezeichnungen,
Rollen-IDs, manuelle Namen, Farben, Reihenfolge) sowie Kanal- und Nachrichten-IDs der
geposteten Beiträge. Mitgliedernamen und Avatare werden ausschließlich zur Anzeige
live abgerufen und **nicht** dauerhaft gespeichert.

## Hinweise

- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.
- Im **Bild**-Modus werden Emojis nicht dargestellt (die Schriften enthalten keine
  Emoji-Glyphen) – nutze dafür den **Embed**- oder **Text**-Modus. Die farbige
  Markierung je Position übernimmt im Bild die Rollen-/Eigenfarbe.
- Je Position werden im Bild bis zu sieben Personen gezeigt, der Rest als
  „+N weitere“.
