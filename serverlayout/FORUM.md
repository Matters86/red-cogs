# 🧩 ServerLayout (Server-Layout)

Speichert das **Layout eines Servers** – Rollen, Kategorien/Kanäle mit Berechtigungen und Server-Einstellungen – und
lädt es auf einen **anderen oder denselben** Server. Mit **Vorschau**, **automatischer Sicherung** vor jedem Laden,
Fortschritt, Abbrechen und Bericht. Bedienbar per Befehl oder im **WebCore-Dashboard** (Download/Upload als Datei).

**Installation**
```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs serverlayout
[p]load serverlayout
```
Voraussetzung: der Cog `webcore` ist installiert und eingerichtet.

**Funktionen**
- Rollen (Name, Farbe, Rechte, Reihenfolge, @everyone), Kanäle aller Art inkl. Forum-Tags und Berechtigungen für Rollen, Server-Einstellungen inkl. Icon/Banner
- Zwei Modi: **Ergänzen** (legt an, passt an, löscht nichts) oder **Exakt angleichen** (löscht zusätzlich Überzähliges – nur nach Eintippen des Server-Namens)
- Vorschau: was angelegt, geändert, gelöscht oder übersprungen wird – mit Grund und Warnungen (Bot-Rechte, Rollen über dem Bot, Community, Boost-Stufe, Limits)
- Automatische Sicherung des Ziel-Servers vor jedem Laden („Automatisch vor dem Laden – …“)
- Keine Nachrichten, Mitglieder, Emojis, Bans oder Webhooks

⚠️ **Exakt angleichen** löscht Kanäle samt Nachrichten unwiderruflich – die Sicherung bringt nur leere Kanäle zurück.

**Befehle**

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]layout save <name> [teile]` | Layout dieses Servers speichern | Administrator |
| `[p]layout list` | Gespeicherte Layouts | Administrator |
| `[p]layout info <name>` | Details | Administrator |
| `[p]layout export <name>` | Als JSON-Datei senden | Administrator |
| `[p]layout status` | Fortschritt / letzter Bericht | Administrator |
| `[p]layout preview <name> [ergänzen\|angleichen] [teile]` | Vorschau | Bot-Owner |
| `[p]layout load <name> [ergänzen\|angleichen] [teile]` | Laden mit Bestätigung | Bot-Owner |
| `[p]layout import [name]` | Datei-Anhang importieren | Bot-Owner |
| `[p]layout rename "<name>" <neu>` | Umbenennen | Bot-Owner |
| `[p]layout delete <name>` | Löschen | Bot-Owner |
| `[p]layout cancel` | Laufenden Vorgang abbrechen | Bot-Owner |
| `[p]layout language <de\|en>` | Sprache der Antworten | Administrator |

Teile: `rollen`, `kanäle`, `einstellungen` (kommagetrennt) oder `alle`.

**Beispiele**
```
[p]layout save Grundgerüst
[p]layout preview Grundgerüst angleichen rollen,kanäle
[p]layout load Grundgerüst ergänzen
```

Im Dashboard (Seite „Server-Layout“ unter `/cogs/serverlayout`, nur Bot-Owner): Layouts verwalten, Server speichern,
Datei hochladen/herunterladen, Vorschau + Laden, Fortschritt und Verlauf.
