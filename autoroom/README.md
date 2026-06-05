# AutoRoom (Autovoiceroom)

Erstellt automatisch temporäre Voicechannels. Betritt jemand einen festgelegten
**Quell-Channel**, legt der Bot einen eigenen Voicechannel an und verschiebt die Person
hinein. Ist der Raum leer, wird er automatisch wieder gelöscht.

Highlights gegenüber gängigen AutoRoom-Cogs:

- **Komplett über das WebCore-Dashboard konfigurierbar** – inkl. Live-Übersicht aller aktiven Räume.
- **Volle Selbstverwaltung** durch die Raum-Besitzer (öffentlich/gesperrt/privat, erlauben/verbieten, umbenennen, Limit, Bitrate, Übernahme).
- **Mehrere Quellen pro Server**, jede mit eigener Zielkategorie, Namensvorlage, Limit und Standard-Sichtbarkeit.
- **Ohne schwere Abhängigkeiten** – Namensvorlagen über einfache Platzhalter (`{user}`, `{game}`, `{num}`), kein Templating-Paket nötig.
- **Robustes Aufräumen** verwaister Räume beim Laden und per Befehl.

## Installation

```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs autoroom
[p]load autoroom
```

Der Bot benötigt die Rechte **Kanäle verwalten** und **Mitglieder verschieben**.

## Schnellstart

1. Einen Quell-Channel festlegen (per Befehl oder im Dashboard):
   ```
   [p]autoroomset addsource "Voice erstellen" [Zielkategorie]
   ```
2. Optional Namensvorlage/Limit/Sichtbarkeit anpassen.
3. Fertig – wer den Quell-Channel betritt, bekommt seinen eigenen Raum.

## Namensvorlagen

In der Vorlage stehen folgende Platzhalter zur Verfügung:

| Platzhalter | Bedeutung |
|---|---|
| `{user}` | Anzeigename der Person |
| `{game}` | aktuell gespieltes Spiel (sonst leer) |
| `{num}` | fortlaufende Nummer (sucht die nächste freie) |

Standardvorlage: `🔊 {user}`

## Befehle – eigener Raum (für alle, in ihrem AutoRoom)

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]autoroom settings` | Zeigt die Einstellungen deines Raums. | im Raum |
| `[p]autoroom public` | Raum öffentlich (jeder sieht + joint). | Besitzer |
| `[p]autoroom locked` | Raum gesperrt (sichtbar, kein Beitritt). | Besitzer |
| `[p]autoroom private` | Raum privat (unsichtbar). | Besitzer |
| `[p]autoroom name <text>` | Raum umbenennen. | Besitzer |
| `[p]autoroom limit <zahl>` | Nutzerlimit (0 = unbegrenzt). | Besitzer |
| `[p]autoroom bitrate <kbps>` | Bitrate setzen. | Besitzer |
| `[p]autoroom allow <@user/@rolle>` | Zutritt erlauben. | Besitzer |
| `[p]autoroom deny <@user/@rolle>` | Zutritt verbieten (wirft anwesende raus). | Besitzer |
| `[p]autoroom claim` | Raum übernehmen, wenn der Besitzer weg ist. | im Raum |
| `[p]autoroom transfer <@user>` | Raum an jemanden im Raum übergeben. | Besitzer |

Diese Befehle gibt es auch als **Slash-Befehle** (`/autoroom …`).

## Befehle – Einrichtung (Admin)

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]autoroomset addsource <channel> [kategorie]` | Quelle anlegen (Räume in Kategorie, sonst wie Quelle). | Admin / Server verwalten |
| `[p]autoroomset removesource <channel>` | Quelle entfernen. | Admin / Server verwalten |
| `[p]autoroomset name <channel> <vorlage>` | Namensvorlage setzen. | Admin / Server verwalten |
| `[p]autoroomset limit <channel> <zahl>` | Standard-Nutzerlimit. | Admin / Server verwalten |
| `[p]autoroomset bitrate <channel> <kbps>` | Standard-Bitrate (0 = Server-Standard). | Admin / Server verwalten |
| `[p]autoroomset visibility <channel> <public/locked/private>` | Standard-Sichtbarkeit. | Admin / Server verwalten |
| `[p]autoroomset textchannel <channel> <true/false>` | Textkanal pro Raum an/aus. | Admin / Server verwalten |
| `[p]autoroomset access <admin/mod> <true/false>` | Dürfen Admin-/Mod-Rollen private Räume sehen? | Admin / Server verwalten |
| `[p]autoroomset cleanup` | Verwaiste, leere Räume aufräumen. | Admin / Server verwalten |
| `[p]autoroomset settings` | Alle Quellen und Einstellungen anzeigen. | Admin / Server verwalten |

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Autovoiceroom**. Dort lassen sich

- alle aktiven Räume serverübergreifend einsehen,
- Quellen pro Server anlegen, bearbeiten und entfernen,
- und der Zugriff von Admin-/Mod-Rollen auf private Räume steuern –

alles über Formulare (POST + CSRF), die direkt in die Bot-Konfiguration schreiben.

## Hinweise

- Mitglieder mit **Administrator**-Recht sehen private Räume ohnehin immer; die `access`-Option
  betrifft Admin-/Mod-Rollen **ohne** dieses Recht.
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.
