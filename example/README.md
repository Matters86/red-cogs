# Example

Beispiel-Cog als Vorlage. Zeigt, wie ein Cog gleichzeitig

- einen **Hybrid-Befehl** (Text + Slash) bereitstellt,
- sich automatisch ins **WebCore-Dashboard** einklinkt,
- und sauber dokumentiert wird (siehe `FORUM.md`).

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs example
[p]load example
```

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]example hello` | Sagt Hallo. | alle |
| `[p]example note` | Zeigt die Notiz des Servers. | alle |
| `[p]example setnote <text>` | Setzt die Server-Notiz. | Admin / Manage Server |

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Example**: Mitgliederzahl und Notiz des
oben rechts gewählten Servers, die Notiz lässt sich direkt speichern. Die Anbindung steckt in
`cog_load`, `cog_unload` und dem `on_webcore_ready`-Listener; `dashboard_page` zeigt das
empfohlene Muster (Server über `visible_guilds`, `?guild=` aus dem globalen Wechsler,
CSRF + Post/Redirect/Get). Genau dieses Muster für eigene Cogs übernehmen – dann greifen die
Rollen-Rechte aus „Zugriff & Rollen“ automatisch.

Das Markup entsteht ausschließlich mit dem UI-Baukasten von WebCore (`ui = request.app["webcore"].ui`,
alle Parameter werden escaped, kein eigenes CSS nötig):

| Baustein | Zweck im Beispiel |
|---|---|
| `ui.hero(icon, "", text)` | Seitenkopf mit Symbol und einem Satz Erklärung |
| `ui.stats([...])` | Kennzahlen (Mitglieder, Notiz gesetzt/leer) |
| `ui.card(titel, inhalt, icon=, desc=)` | Karte „Server-Notiz“ |
| `ui.form(action, inhalt, csrf=, hidden=, savebar=True)` | Formular inkl. CSRF-Token und Leiste „Ungespeicherte Änderungen“ |
| `ui.grid(...)`, `ui.field(label, control, help=)` | Formular-Raster mit Hilfetext |
| `ui.text_input(...)`, `ui.save_row()` | Eingabefeld und Speichern-Knopf |

Weitere Bausteine (als Kommentar in `dashboard_page` gezeigt): `ui.switch` (Schalter statt
Checkbox), `ui.number` (Zahl mit Einheit), `ui.select` (mit `multiple=True` als Chip-Auswahl),
`ui.tab` (Reiter), `ui.table`/`ui.row` (Tabellen, `search=True` für Filter), `ui.callout`,
`ui.empty`, `ui.badge` und `ui.button(..., kind="danger", confirm="…")` für Aktionen mit Rückfrage.
Vorbild für eine größere Seite: `tickets/dashboard.py`.
