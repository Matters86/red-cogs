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
