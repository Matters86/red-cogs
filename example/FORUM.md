# Example

Beispiel-Cog als Vorlage – ein Befehl plus eine eigene Seite im Web-Dashboard.

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
| `[p]example setnote <text>` | Setzt die Server-Notiz. | Admin / „Server verwalten" |

## Dashboard
Nach dem Laden erscheint im Web-Dashboard automatisch der Tab **Example** mit einer
Übersicht aller Server und ihrer Notizen.

## Hinweise
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.
