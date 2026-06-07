# Commands

Zeigt **alle Befehle aller Cogs** im Web-Dashboard – mit Stufen-Spalten
(Jeder/Mod/Admin/Owner), einer exakten Prüfung pro Mitglied, Suche/Filter, Ausblenden
einzelner Einträge und Markdown-Export. Neue Cogs erscheinen automatisch. In Discord
zeigt `[p]meinebefehle` jedem seine nutzbaren Befehle. Keine zusätzlichen Abhängigkeiten.

## Installation
```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs commands
[p]load commands
```

## Befehle
| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]meinebefehle [mitglied] [dm]` | Deine nutzbaren Befehle, gruppiert nach Cog (optional Mitglied prüfen / per DM). | alle (fremdes Mitglied: Mod) |
| `[p]befehlsliste verstecken <cog\|command> <name>` | Cog/Befehl ausblenden. | Owner |
| `[p]befehlsliste zeigen <cog\|command> <name>` | Wieder einblenden. | Owner |
| `[p]befehlsliste status` | Kurzübersicht + Dashboard-Status. | Owner |
| `[p]befehlsliste sprache <de\|en>` | Sprache der Nutzer-Ausgabe (pro Server). | Owner |

Alles auch als **Slash-Befehle** (`/meinebefehle`, `/befehlsliste …`).

## Dashboard
Nach dem Laden erscheint der Tab **Befehle**: gruppierte Tabelle mit Stufen-Spalten und
Rechte-Badges, ein Prüf-Formular „Mitglied prüfen" (Server + ID/Name) für das exakte
Ergebnis pro Befehl, Volltextsuche und Filter nach Cog/Stufe, Schalter zum Aus-/Einblenden
sowie ein Markdown-Export.

## Gut zu wissen
- **Owner-Spalte** = Bot-Owner. Geforderte Discord-Rechte stehen als Badge `oder: …` – wer sie
  hat, darf den Befehl auch ohne die Stufe.
- `[p]meinebefehle` (eigene Befehle) prüft exakt über Reds `can_run` – inklusive Permissions-Cog.
- Die Fremdprüfung im Dashboard rechnet mit Stufe + Rechten; Permissions-Cog-Einzelregeln und
  befehlseigene Checks fließen dort nicht ein (Befehle sind mit „Extra-Prüfung" markiert).

## Hinweise
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung: `webcore` ist geladen und eingerichtet. Das Aus-/Einblenden braucht die
  aktuelle WebCore-Version (POST/CSRF); die Anzeige selbst funktioniert auch ohne.
