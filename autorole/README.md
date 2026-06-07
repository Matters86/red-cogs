# Autorole

Vergibt **neuen Mitgliedern beim Beitritt automatisch Rollen**. Gegenüber üblichen Autorole-Cogs
legt dieser Cog den Fokus auf **Sicherheit und sauberes Verhalten**: Er respektiert die native
Discord-Regelverifizierung, prüft vor jeder Vergabe, ob eine Rolle überhaupt zuweisbar ist, und
bringt Schutzmechanismen gegen Raids mit.

Highlights:

- **Mehrere Beitritts-Rollen** gleichzeitig pro Server.
- **Respektiert die Discord-Regelverifizierung (Membership Screening):** Rollen werden – sofern
  aktiv – erst vergeben, wenn das Mitglied die Regeln akzeptiert hat, nicht schon beim reinen
  Beitritt. Modus wählbar (automatisch erkennen / immer warten / nie warten).
- **Zuweisbarkeits-Prüfung vor jeder Vergabe:** `@everyone`, von Integrationen verwaltete Rollen
  und Rollen über der höchsten Bot-Rolle werden erkannt und nicht (fehlschlagend) versucht,
  sondern sichtbar markiert.
- **Anti-Raid:** optionale **Verzögerung** (0–3600 s) und **Mindest-Kontoalter** (in Stunden),
  bevor Rollen vergeben werden.
- **Getrennte Bot-Rollen:** an beitretende Bots werden eigene Rollen vergeben (ohne auf Screening
  zu warten).
- **Sichere Sticky-Rollen:** nur ausdrücklich markierte Rollen werden beim Verlassen gemerkt und
  beim Wiederbeitritt wiederhergestellt – also gezielt z. B. ein „Verifiziert\"-Status, **nicht**
  pauschal alle Rollen (damit keine Straf-/Mute-Rolle zurückkehrt).
- **Bestehende Mitglieder nachträglich versorgen** per Befehl oder Dashboard-Knopf.
- **Mehrsprachig** (Deutsch/Englisch) für die Bot-Antworten, Standard Deutsch.
- **Komplett über das WebCore-Dashboard konfigurierbar.**

## Installation

```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs autorole
[p]load autorole
```

Voraussetzungen:

- Der Bot braucht das Recht **Rollen verwalten** und muss in der Rollenliste **über** den zu
  vergebenden Rollen stehen.
- Der **Server-Mitglieder-Intent** (Members Intent) muss aktiv sein, damit Beitritte erkannt
  werden (`[p]intents` bzw. im Discord Developer Portal).

## Schnellstart

```
[p]autorole add @Mitglied
[p]autorole toggle
```

Ab sofort erhält jedes neue (menschliche) Mitglied die Rolle **@Mitglied** – bei aktiver
Regelverifizierung erst, nachdem es die Regeln akzeptiert hat.

## Regelverifizierung (Membership Screening)

Hat ein Server die Discord-Funktion **„Mitglieder müssen den Community-Regeln zustimmen\"** aktiv,
sind frisch beigetretene Mitglieder zunächst „in Prüfung\" (pending) und sehen den Server nur
eingeschränkt. Der Modus steuert, wann Autorole zuschlägt:

| Modus | Verhalten |
|---|---|
| `auto` (Standard) | Erkennt automatisch, ob der Server Regelverifizierung nutzt. Falls ja: Rollen erst nach Zustimmung. Falls nein: Rollen direkt beim Beitritt. |
| `on` | Wartet **immer** auf die Zustimmung (nur sinnvoll, wenn die Funktion auch aktiv ist). |
| `off` | Vergibt **immer sofort** beim Beitritt, unabhängig von der Verifizierung. |

Bots durchlaufen kein Screening und erhalten ihre Bot-Rollen direkt.

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]autorole toggle` | Automatische Vergabe an-/ausschalten. | Admin / Rollen verwalten |
| `[p]autorole add <rolle>` | Rolle zu den Beitritts-Rollen hinzufügen. | Admin / Rollen verwalten |
| `[p]autorole remove <rolle>` | Rolle aus den Beitritts-Rollen entfernen. | Admin / Rollen verwalten |
| `[p]autorole botadd <rolle>` | Rolle für beitretende **Bots** hinzufügen. | Admin / Rollen verwalten |
| `[p]autorole botremove <rolle>` | Bot-Rolle entfernen. | Admin / Rollen verwalten |
| `[p]autorole sticky <rolle>` | Rolle als Sticky markieren/entmarkieren (wird gemerkt & wiederhergestellt). | Admin / Rollen verwalten |
| `[p]autorole delay <sekunden>` | Verzögerung vor der Vergabe setzen (0–3600). | Admin / Rollen verwalten |
| `[p]autorole age <stunden>` | Mindest-Kontoalter setzen (0 = aus). | Admin / Rollen verwalten |
| `[p]autorole screening <auto/on/off>` | Verhalten bei Regelverifizierung. | Admin / Rollen verwalten |
| `[p]autorole language <de/en>` | Sprache der Bot-Antworten. | Admin / Rollen verwalten |
| `[p]autorole settings` | Aktuelle Server-Einstellungen anzeigen. | Admin / Rollen verwalten |
| `[p]autorole applyall` | Konfigurierte Rollen an alle passenden bestehenden Mitglieder vergeben. | Admin / Server verwalten |

Diese Befehle gibt es auch als **Slash-Befehle** (`/autorole …`).

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Autorole**. Dort lassen sich

- der Status auf einen Blick sehen (aktiv?, Anzahl Mitglieder-/Bot-Rollen, Regelverifizierung),
- **Warnungen** einsehen (fehlt dem Bot „Rollen verwalten\"? sind konfigurierte Rollen nicht
  zuweisbar?),
- alle Einstellungen über ein Formular setzen: An/Aus, Sprache, Screening-Modus, Verzögerung,
  Mindest-Kontoalter sowie die drei Rollenlisten (Mitglieder-, Bot- und Sticky-Rollen),
- und mit **„Jetzt anwenden\"** die Rollen an alle passenden bestehenden Mitglieder vergeben –

alles über Formulare (POST + CSRF), die direkt in die Bot-Konfiguration schreiben.

## Hinweise

- **Bot-Position entscheidet:** Der Bot kann nur Rollen vergeben, die **unter** seiner höchsten
  Rolle stehen. Nicht zuweisbare Rollen werden im Dashboard und in `settings` mit ⚠ markiert.
- **Verzögerung** hilft zusätzlich gegen Konflikte mit dem Mutes-Cog bei sehr schnellem
  Wieder-Beitritt – ein paar Sekunden genügen meist.
- **Sticky-Rollen** bewusst sparsam einsetzen: gespeichert wird nur, was ausdrücklich als Sticky
  markiert ist. So kommt eine entfernte Straf-/Mute-Rolle nicht durch einen Rejoin zurück.
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.
