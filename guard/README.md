# Guard

Schutz-Cog für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – **Spamschutz**, **Honeypot** und **Raid-Notmodus** in einem, mehrsprachig und komplett über das WebCore-Dashboard steuerbar. **Ohne externe pip-Abhängigkeiten.**

Zwei pro Server unabhängig schaltbare Module plus ein automatischer Notmodus. Aktionen erfolgen **ohne DM** an Ausgelöste, werden in einen Log-Kanal geschrieben (optional zusätzlich in Reds `modlog`) und als Verlauf fürs Dashboard gespeichert.

## Funktionen

- **Honeypot** – ein Köder-Kanal, in dem reguläre Mitglieder nie schreiben. Wer dort postet, wird automatisch entfernt. Aktion pro Server wählbar: Bann, Softban, Kick oder Timeout. Kanal per Befehl neu anlegen **oder** bestehenden markieren.
- **Spamschutz mit Punktesystem** – mehrere Heuristiken füttern ein Punktekonto; Schwellen lösen eine Eskalationsleiter aus (**verwarnen → Timeout → Kick → Bann**). Bleibt es ruhig, verfallen die Punkte nach einer einstellbaren Zeit.
- **Heuristiken** – Nachrichten-Rate, Wiederholungen (auch kanalübergreifend), Massen-Erwähnungen (inkl. `@everyone`/`@here`), Einladungslinks, optional alle externen Links, Anhang-/Emoji-/Zeilen-Walls und sehr neue Konten (wirken als Verstärker).
- **Raid-Notmodus (Lockdown)** – zu viele Beitritte in kurzer Zeit oder ein Befehl versetzen den Server in einen Lockdown: Slowmode, optional Einladungen pausieren (falls von Discord unterstützt) und neue Beitritte automatisch behandeln. **Übersteht Bot-Neustarts** und endet nach einer Frist automatisch.
- **Ausnahmen** – Owner, Admins/„Server verwalten", der Bot selbst und Reds Immunität (`[p]immune`) sind immer ausgenommen. Dazu eigene Whitelist für Rollen, Kanäle (nur Spamschutz) und Nutzer. Andere Bots ignorieren ist abschaltbar.
- **Logging** – Embeds in einem Log-Kanal (Wer, Aktion, Regel, Kanal, Punkte) plus persistenter Verlauf im Dashboard; optional zusätzlich als Fall in Reds `modlog`.
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (aktuell `de`, `en`).
- **Dashboard** – jede Einstellung, der Notmodus-Schalter und der Verlauf direkt im Browser.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs guard
[p]load guard
```

## Schnellstart

```
[p]guardset honeypot create honeypot   # Köder-Kanal anlegen und Honeypot aktivieren
[p]guardset module spam on             # Spamschutz einschalten
[p]guardset logchannel #mod-log        # Log-Kanal setzen
[p]guardset settings                   # aktuelle Werte + Dashboard-Link
```

Der Feinschliff (Schwellen, Punkte, Eskalationsstufen, Raid-Werte) geht am bequemsten über das Dashboard.

> **Wichtig zum Honeypot:** Lege den Kanal **oben** in der Kanalliste an, damit Bots ihn als Erstes sehen, und stelle sicher, dass die Bot-Rolle über den betroffenen Mitgliedern steht (sonst kann der Bot nicht bannen/kicken). Schreibrecht für `@everyone` lassen – die Falle lebt davon, dass dort gepostet werden *kann*.

## Befehle

Einstellungen (`guardset`) – erfordern „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]guardset module <honeypot\|spam> <on\|off>` | Ein Modul ein-/ausschalten |
| `[p]guardset honeypot create [name]` | Neuen Honeypot-Kanal anlegen und aktivieren |
| `[p]guardset honeypot set <kanal>` | Bestehenden Kanal als Honeypot markieren und aktivieren |
| `[p]guardset honeypot disable` | Honeypot deaktivieren |
| `[p]guardset honeypot action <ban\|softban\|kick\|timeout>` | Aktion bei Auslösung setzen |
| `[p]guardset logchannel [kanal]` | Log-Kanal setzen (ohne Angabe: Log-Kanal entfernen) |
| `[p]guardset whitelistrole <rolle>` | Rolle ausnehmen (Umschalter) |
| `[p]guardset whitelistuser <nutzer>` | Nutzer ausnehmen (Umschalter) |
| `[p]guardset whitelistchannel <kanal>` | Kanal vom Spamschutz ausnehmen (Umschalter) |
| `[p]guardset language <de\|en>` | Sprache setzen |
| `[p]guardset settings` | Aktuelle Einstellungen und Dashboard-Link anzeigen |

Notmodus (manuell) – erfordert „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]lockdown on` | Notmodus sofort aktivieren |
| `[p]lockdown off` | Notmodus beenden |

## So funktioniert das Punktesystem

Jede ausgelöste Heuristik vergibt Punkte (pro Heuristik einstellbar). Die Punkte einer Person summieren sich und **verfallen nach `decay`-Sekunden** wieder. Erreicht die Summe eine Schwelle, wird die zugehörige Stufe ausgeführt – immer nur die höchste erreichte, und keine Stufe doppelt, solange die Punkte nicht verfallen sind:

| Stufe | Standard-Schwelle | Aktion |
|---|---|---|
| Verwarnen | 3 Punkte | nur protokolliert (keine DM) |
| Timeout | 6 Punkte | Timeout (Dauer einstellbar) |
| Kick | 9 Punkte | Kick |
| Bann | 12 Punkte | Bann (löscht Nachrichten der letzten X Sekunden) |

Standard-Punkte: Einladungslink 5, Erwähnungen 4, Rate 3, Wiederholung 3, Link/Wall/neues Konto je 2. **Neue Konten** geben nur dann Zusatzpunkte, wenn ohnehin eine andere Heuristik angeschlagen hat – ein neues, harmloses Mitglied wird so nicht bestraft. Die auslösende Nachricht wird (einstellbar) gelöscht.

## Notmodus / Lockdown

Schlägt die Raid-Erkennung an (zu viele Beitritte im Zeitfenster) oder wird `[p]lockdown on` genutzt, passiert Folgendes: in allen Textkanälen wird Slowmode gesetzt (die vorherigen Werte werden gemerkt und beim Beenden wiederhergestellt), Einladungen werden – sofern Discord/discord.py das unterstützt – pausiert, und neue Beitritte werden je nach Einstellung gekickt, getimeoutet oder durchgelassen. Der Zustand wird **gespeichert**, übersteht also Neustarts, und endet nach `lockdown_auto_minutes` automatisch (oder per `[p]lockdown off`).

## Dashboard

Im WebCore-Dashboard unter **Guard** (`/cogs/guard`):

- **Statistik-Kacheln** – Auslösungen gesamt, letzte 24 h, Status von Honeypot/Spamschutz/Notmodus.
- **Notmodus-Schalter** – Lockdown mit einem Klick aktivieren oder beenden.
- **Einstellungen** – Module, Honeypot, alle Heuristiken samt Schwellen, das komplette Punkte-/Eskalationssystem, Raid-/Notmodus-Optionen, Log-Kanal, Sprache und die Whitelist.
- **Verlauf** – die letzten Aktionen mit Zeit, Auslöser, Nutzer, Regel, Aktion und Punkten.

## Hinweise

- **Standard-Aktion Honeypot = `softban`** (Kick samt Löschen der letzten Nachrichten – die schonendste wirksame Variante). Auf `ban`, `kick` oder `timeout` umstellbar per Befehl oder Dashboard.
- **`modlog`-Spiegelung ist standardmäßig an**, greift aber nur, wenn `modlog` auf dem Server eingerichtet ist; Fehler dort beeinträchtigen die Moderation nie. Im Dashboard abschaltbar.
- Es werden **keine Nachrichteninhalte** dauerhaft gespeichert – nur Metadaten der Aktion (siehe `info.json`).
- Datenschutz/Hosting: Das Dashboard nur hinter HTTPS-Reverse-Proxy betreiben; Zugriff haben ausschließlich Bot-Owner.
