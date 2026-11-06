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
Nach dem Laden erscheint im Web-Dashboard automatisch der Tab **Example** – mit Mitgliederzahl
und Notiz des gewählten Servers (direkt im Browser änderbar).

## Hinweise
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.

## Einheitliche Eingabegrenze

Server-Notizen dürfen über Dashboard und `[p]example setnote` höchstens **500 Zeichen** enthalten. Längere Eingaben werden mit einer verständlichen Meldung abgelehnt; die vorhandene Notiz bleibt erhalten. Die Vorlage zeigt damit dieselbe Validierung in beiden Bedienwegen.
