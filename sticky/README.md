# Sticky

Hält eine Nachricht am **unteren Ende eines Kanals** fest. Sobald jemand im Kanal schreibt,
löscht der Bot seine alte Sticky und postet sie unten neu – so „klebt" sie immer am Ende.

Highlights:

- **Text- oder Embed-Modus** pro Kanal (Titel, Farbe, Bild, Footer).
- **Cooldown gegen Spam/Rate-Limits** – in aktiven Kanälen wird höchstens alle paar Sekunden neu gepostet (Trailing-Debounce), kein Geflacker.
- **Webhook-Modus** (optional) – Sticky mit eigenem Namen und Avatar.
- **Platzhalter** im Text: `{membercount}`, `{servername}`, `{channel}`, `{channelname}`.
- **Andere Bots optional ignorieren**, damit deren Nachrichten kein Neu-Posten auslösen.
- **Mehrsprachig** (Deutsch/Englisch) für die Bot-Antworten, Standard Deutsch.
- **Komplett über das WebCore-Dashboard konfigurierbar** – inkl. Live-Übersicht aller Stickies.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs sticky
[p]load sticky
```

Der Bot benötigt im Zielkanal die Rechte **Nachrichten senden** und **Nachrichten verwalten**
(zum Löschen der alten Sticky). Für den Webhook-Modus zusätzlich **Webhooks verwalten**.

## Schnellstart

```
[p]sticky set #regeln Willkommen! Bitte lies die Regeln. Mitglieder: {membercount}
```

Ab sofort wandert die Nachricht automatisch immer ans Ende von `#regeln`.

## Platzhalter

| Platzhalter | Bedeutung |
|---|---|
| `{membercount}` | aktuelle Mitgliederzahl |
| `{servername}` / `{server}` | Servername |
| `{channel}` | Erwähnung des Kanals |
| `{channelname}` | Name des Kanals |

## Befehle

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]sticky set <channel> <text>` | Text-Sticky für einen Kanal setzen. | Mod / Nachrichten verwalten |
| `[p]sticky embed <channel> <text>` | Embed-Sticky setzen (Titel/Farbe/Bild im Dashboard). | Mod / Nachrichten verwalten |
| `[p]sticky remove <channel>` | Sticky eines Kanals entfernen. | Mod / Nachrichten verwalten |
| `[p]sticky toggle <channel>` | Sticky an-/ausschalten (ohne sie zu löschen). | Mod / Nachrichten verwalten |
| `[p]sticky refresh <channel>` | Sticky sofort neu posten (umgeht Cooldown). | Mod / Nachrichten verwalten |
| `[p]sticky show <channel>` | Konfiguration einer Sticky anzeigen. | Mod / Nachrichten verwalten |
| `[p]sticky list` | Alle Stickies des Servers auflisten. | Mod / Nachrichten verwalten |
| `[p]sticky cooldown <sekunden>` | Cooldown setzen (0–3600). | Admin / Server verwalten |
| `[p]sticky ignorebots <true/false>` | Nachrichten anderer Bots (nicht) auslösen lassen. | Admin / Server verwalten |
| `[p]sticky language <de/en>` | Sprache der Bot-Antworten. | Admin / Server verwalten |
| `[p]sticky settings` | Aktuelle Server-Einstellungen anzeigen. | Admin / Server verwalten |

Diese Befehle gibt es auch als **Slash-Befehle** (`/sticky …`).

## Dashboard

Ist `webcore` geladen, erscheint automatisch der Tab **Sticky**. Dort lassen sich

- alle Stickies serverübergreifend einsehen (Modus, Status, Posten-via, Vorschau),
- pro Kanal eine Sticky anlegen/bearbeiten (Text oder Embed inkl. Titel, Farbe, Bild, Footer),
- der Webhook-Modus samt Name/Avatar einstellen,
- sowie Sprache, Cooldown und „andere Bots ignorieren" setzen –

alles über Formulare (POST + CSRF), die direkt in die Bot-Konfiguration schreiben und die
Sticky anschließend sofort neu posten.

## Hinweise

- **Kein Message-Content-Intent nötig**: der Cog reagiert nur auf das Ereignis „neue Nachricht im
  Kanal", nicht auf deren Inhalt.
- **Cooldown**: `0` = sofort bei jeder Nachricht (kann in sehr aktiven Kanälen flackern und
  Rate-Limits auslösen). Empfehlung: wenige Sekunden.
- **Nach einem Bot-Neustart** wird die Sticky bei der nächsten Nachricht sauber neu verankert –
  die alte Nachricht wird dabei gelöscht.
- Slash-Befehle ggf. mit `[p]slash sync` aktivieren.
- Voraussetzung für das Dashboard: der Cog `webcore` ist geladen und eingerichtet.
