# Commands

Listet **alle Befehle aller geladenen Cogs** im WebCore-Dashboard – inklusive der
Frage, *wer* sie nutzen darf. Neue Cogs erscheinen automatisch, sobald sie geladen
sind; nichts muss von Hand gepflegt werden.

Highlights:

- **Stufen-Spalten** pro Befehl: **Jeder / Mod / Admin / Owner** (Owner = Bot-Owner).
  Ein &#10003; zeigt, ab welcher Red-Stufe der Befehl freigegeben ist.
- **Exakte Mitglieds-Prüfung** – Server + Mitglied (ID oder Name) wählen und für jeden
  Befehl ein klares „darf / gesperrt" sehen. (Das Dashboard ist owner-only, deshalb gibt
  es ein wählbares Subjekt.)
- **Detail-Metadaten**: Signatur, Aliase, Subbefehle (eingerückt), geforderte Discord-Rechte,
  Gruppen-, „deaktiviert"- und „versteckt"-Marker.
- **Suche & Filter** direkt im Dashboard (Volltext, nach Cog, nach Stufe) – ohne Neuladen.
- **Ausblenden**: einzelne Cogs oder Befehle per Klick aus Liste und Export nehmen
  (umschaltbar, jederzeit wieder einblendbar).
- **Markdown-Export** der (gefilterten) Liste als Datei.
- **In Discord**: `[p]meinebefehle` zeigt jedem seine nutzbaren Befehle – optional per DM.
- **Mehrsprachig** (Deutsch/Englisch) für die Bot-Antworten, Standard Deutsch.
- **Keine zusätzlichen Abhängigkeiten** – reine Red-/discord.py-Bordmittel.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs commands
[p]load commands
```

Voraussetzung für die Dashboard-Seite ist ein geladener und eingerichteter `webcore`-Cog.

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]meinebefehle [mitglied] [dm]` | Zeigt dir deine auf diesem Server nutzbaren Befehle (gruppiert nach Cog). Optional ein Mitglied prüfen und/oder `dm: true`. | alle (fremdes Mitglied: Mod) |
| `[p]befehlsliste verstecken <cog\|command> <name>` | Einen Cog oder Befehl aus Liste/Export ausblenden. | Owner |
| `[p]befehlsliste zeigen <cog\|command> <name>` | Einen ausgeblendeten Cog/Befehl wieder anzeigen. | Owner |
| `[p]befehlsliste status` | Kurzübersicht: Anzahl Cogs/Befehle, Ausgeblendetes, Dashboard-Status, Sprache. | Owner |
| `[p]befehlsliste sprache <de\|en>` | Sprache der Nutzer-Ausgabe für diesen Server. | Owner |

Diese Befehle gibt es auch als **Slash-Befehle** (`/meinebefehle`, `/befehlsliste …`).

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Befehle**. Dort gibt es:

- Kennzahlen (Cogs, Befehle gesamt, angezeigt, ausgeblendet),
- die nach Cog gruppierte Tabelle mit Stufen-Spalten, Rechte-Badges und Beschreibung,
- ein Prüf-Formular „Mitglied prüfen" (Server + ID/Name) → zusätzliche Spalte mit dem
  exakten Ergebnis pro Befehl,
- Volltextsuche sowie Filter nach Cog und Stufe,
- pro Zeile bzw. pro Cog einen Schalter zum Aus-/Einblenden,
- Links für „ausgeblendete anzeigen" und „Markdown-Export".

## Wie die Rechte interpretiert werden

- Die **Stufen-Spalten** stammen aus Reds Privileg-Modell (`PrivilegeLevel`): NONE → *Jeder*,
  MOD → *Mod*, ADMIN → *Admin*, GUILD_OWNER → Badge *Server-Owner*, BOT_OWNER → *Owner*.
- **Geforderte Discord-Rechte** (z. B. „Server verwalten") lassen sich nicht sauber auf eine
  Stufe abbilden und stehen deshalb als Badge `oder: …`. Wer das Recht hat, darf den Befehl
  auch ohne die Stufe (entspricht `admin_or_permissions`).
- Die **Eigenprüfung** in `[p]meinebefehle` (ohne Mitglied) nutzt Reds `can_run` und ist
  damit vollständig – **inklusive** der Einzelregeln der Permissions-Cog und befehlseigener
  Checks.
- Die **Fremdprüfung** (Dashboard-Mitgliedsprüfung bzw. `[p]meinebefehle @jemand`) rechnet mit
  Privileg-Stufe **und** Discord-Rechten. Einzelregeln der Permissions-Cog, befehlseigene
  `checks` und kanal-spezifische Overrides fließen hier **nicht** ein; betroffene Befehle sind
  mit „Extra-Prüfung" markiert.

## Hinweise

- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Das Aus-/Einblenden im Dashboard nutzt POST-Formulare; dafür muss die aktuelle WebCore-Version
  (mit POST-/CSRF-Unterstützung) auf dem Bot laufen. Die reine Anzeige funktioniert auch ohne.
- Mitglieder werden aus dem Bot-Cache aufgelöst; sehr selten aktive Mitglieder sind ggf. erst
  nach einer Interaktion auffindbar.
