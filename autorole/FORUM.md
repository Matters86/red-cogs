# Autorole

Vergibt **neuen Mitgliedern beim Beitritt automatisch Rollen** – mit Fokus auf Sicherheit:
respektiert die native Discord-**Regelverifizierung**, prüft vor jeder Vergabe die
**Zuweisbarkeit** jeder Rolle, bringt **Anti-Raid** (Verzögerung + Mindest-Kontoalter), getrennte
**Bot-Rollen** und sichere **Sticky-Rollen**. Mehrsprachig (Deutsch/Englisch) und komplett über
das Web-Dashboard konfigurierbar.

## Installation
```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs autorole
[p]load autorole
```
Bot-Recht: **Rollen verwalten** (und in der Rollenliste **über** den zu vergebenden Rollen).
Außerdem muss der **Mitglieder-Intent** aktiv sein.

## Schnellstart
```
[p]autorole add @Mitglied
[p]autorole toggle
```
Jedes neue Mitglied bekommt nun **@Mitglied** – bei aktiver Regelverifizierung erst nach Zustimmung.

## Verbesserungen gegenüber üblichen Autorole-Cogs
- **Respektiert die Regelverifizierung (Membership Screening):** Rollen erst nach Zustimmung statt
  blind beim Beitritt (Modus `auto`/`on`/`off`). Ersetzt den alten „Zustimmungs-Nachricht\"-Trick.
- **Zuweisbarkeits-Prüfung:** `@everyone`, verwaltete (Integrations-)Rollen und Rollen über der
  Bot-Rolle werden erkannt und sichtbar markiert statt stillschweigend fehlzuschlagen.
- **Anti-Raid:** Verzögerung (0–3600 s) + Mindest-Kontoalter (Stunden).
- **Getrennte Bot-Rollen:** beitretende Bots bekommen eigene Rollen (ohne Screening).
- **Sichere Sticky-Rollen:** nur markierte Rollen werden gemerkt/wiederhergestellt – keine
  pauschale Wiederherstellung, damit keine Mute-/Straf-Rolle per Rejoin zurückkommt.
- **Rollen-Panels (Self-Service):** gepostete Nachricht mit **Buttons oder Dropdown** zum
  Selbstvergeben von Rollen – Verhalten pro Panel (Toggle / nur vergeben / nur eine Rolle),
  funktioniert auch nach einem Neustart weiter.

## Regelverifizierung
| Modus | Verhalten |
|---|---|
| `auto` | Erkennt automatisch: Server nutzt Verifizierung → Rolle nach Zustimmung; sonst → sofort. |
| `on` | Wartet **immer** auf die Zustimmung. |
| `off` | Vergibt **immer sofort** beim Beitritt. |

## Befehle (Admin / „Rollen verwalten\")
| Befehl | Beschreibung |
|---|---|
| `[p]autorole toggle` | Automatische Vergabe an/aus. |
| `[p]autorole add <rolle>` | Beitritts-Rolle hinzufügen. |
| `[p]autorole remove <rolle>` | Beitritts-Rolle entfernen. |
| `[p]autorole botadd <rolle>` | Rolle für beitretende Bots hinzufügen. |
| `[p]autorole botremove <rolle>` | Bot-Rolle entfernen. |
| `[p]autorole sticky <rolle>` | Rolle als Sticky markieren/entmarkieren. |
| `[p]autorole delay <sekunden>` | Verzögerung 0–3600 s. |
| `[p]autorole age <stunden>` | Mindest-Kontoalter (0 = aus). |
| `[p]autorole screening <auto/on/off>` | Verhalten bei Regelverifizierung. |
| `[p]autorole language <de/en>` | Sprache der Bot-Antworten. |
| `[p]autorole settings` | Einstellungen anzeigen. |

## Befehle (Admin / „Server verwalten\")
| Befehl | Beschreibung |
|---|---|
| `[p]autorole applyall` | Rollen an alle passenden bestehenden Mitglieder vergeben. |

Gibt es auch als Slash-Befehle (`/autorole …`).

## Rollen-Panels (Buttons & Dropdown)
Der Bot postet eine Nachricht mit **Buttons** oder einem **Dropdown** darunter; Mitglieder klicken
und erhalten/verlieren die Rolle. Beliebig viele Panels pro Server, jedes einzeln einstellbar:
**Darstellung** (Buttons/Dropdown), **Verhalten** (`Toggle` / `Nur vergeben`), optional **nur eine
Rolle gleichzeitig** (z. B. Farben) und **Aussehen** (Embed oder Text). Es greift dieselbe
Zuweisbarkeits-Prüfung; die Antwort sieht nur die klickende Person (ephemer); die Panels
funktionieren auch **nach einem Neustart** weiter. Feineinstellungen (Emoji, Button-Farbe, Texte)
am besten im **Dashboard**.

| Befehl (Admin / „Rollen verwalten") | Beschreibung |
|---|---|
| `[p]autorole panel list` | Panels auflisten (ID, Kanal, Stil, Status). |
| `[p]autorole panel create <name>` | Neues, leeres Panel anlegen. |
| `[p]autorole panel addrole <id> <rolle>` | Rolle zum Panel hinzufügen. |
| `[p]autorole panel removerole <id> <rolle>` | Rolle aus dem Panel entfernen. |
| `[p]autorole panel post <id> [#kanal]` | Panel posten/aktualisieren. |
| `[p]autorole panel delete <id>` | Panel samt Nachricht löschen. |

## Dashboard
Mit geladenem `webcore` erscheint der Tab **Autorole**: Status-Übersicht (aktiv?, Anzahl
Mitglieder-/Bot-Rollen, Regelverifizierung), Warnungen (fehlendes Recht „Rollen verwalten\" oder
nicht zuweisbare Rollen), ein Formular für alle Einstellungen (An/Aus, Sprache, Screening,
Verzögerung, Kontoalter, die drei Rollenlisten) sowie ein Knopf **„Jetzt anwenden\"** für
bestehende Mitglieder – alles per Formular. Unter **Rollen-Panels** legst du beliebig viele Self-Service-Panels (Buttons/Dropdown) an, pflegst Rollen samt Emoji/Farbe und postest sie.

## Hinweise
- Der Bot vergibt nur Rollen **unter** seiner höchsten Rolle; nicht zuweisbare Rollen werden mit ⚠ markiert.
- Verzögerung entschärft zusätzlich Konflikte mit dem Mutes-Cog bei schnellem Rejoin.
- Sticky-Rollen sparsam einsetzen (es wird nur gespeichert, was als Sticky markiert ist).
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: `webcore` ist geladen und eingerichtet.
