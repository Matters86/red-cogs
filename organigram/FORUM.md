# Organigram

Postet **Server-Organigramme** nach Discord – als Bild, Embed oder Text. Beliebig viele
benannte Organigramme pro Server, komplett über das Web-Dashboard konfigurierbar.

**Highlights**
- Positionen aus Discord-**Rollen** (Mitglieder automatisch) **und** manuellen Namen.
- **Drei Modi, pro Post wählbar:** Bild · Embed · Text.
- **Fünf Bild-Muster:** Baum, Abteilungen, Pyramide, Kompaktliste, Karten – mit Avataren
  und Rollenfarben im Dashboard-Look.
- **Automatische Aktualisierung** bei Rollen-/Mitgliederänderungen.
- **Live-Vorschau** und **PNG-Export** im Dashboard.

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

`modus` = `bild` · `embed` · `text` (optional; sonst Standard des Organigramms). Alias: `org`.

## Dashboard
Ist `webcore` geladen, erscheint automatisch der Tab **Organigramm**: Organigramme anlegen,
Muster/Modus/Farbe wählen, Positionen pflegen (Rolle + manuelle Namen, übergeordnete Position,
Emoji, Farbe, Reihenfolge), Live-Vorschau ansehen, PNG herunterladen und in einen Kanal posten.

## Hinweise
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Dashboard benötigt den geladenen Cog `webcore`.
- Emojis erscheinen nur im **Embed**- und **Text**-Modus (im Bild dient die Farbe als Markierung).
