# Changelog

Server-Updates (Changelogs) für [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) – Team-Mitglieder füllen ein **Modal** aus, der Bot postet daraus ein **einheitliches Embed** im festgelegten Kanal. Mehrsprachig, mit eigener Seite im WebCore-Dashboard.

Der Befehl **`/changelog`** öffnet ein Popup-Formular mit den Feldern **Titel, Neu, Geändert, Fixes, Hinweis**. Beim Absenden baut der Bot ein sauberes Update-Embed (Bullet-Listen, Kategorie-Emoji, Fußzeile mit Datum und Name) und postet es – optional mit einem Rollen-Ping davor.

## Funktionen

- **Posten per Modal** – `/changelog` öffnet ein Formular; kein manuelles Embed-Basteln.
- **Einheitliches Embed** – Titel, Abschnitte *Neu/Geändert/Fixes* als Bullet-Listen, optionaler **Hinweis** (fett, mit ⚠️), Fußzeile mit Datum + Name.
- **Kategorie pro Changelog wählbar** – die postende Person wählt beim Befehl ein Emoji für den „Neu\"-Bereich (z. B. 🚗/🌾/⚙️); die Auswahl-Liste ist pro Server konfigurierbar.
- **Ziel-Kanal fest pro Server** – nicht vom User wählbar, damit Changelogs immer am richtigen Ort landen.
- **Rechte pro Server** – nur festgelegte Rollen (plus Admins) dürfen posten; serverseitig geprüft.
- **Optionaler Ping** – eine `@Updates`-Rolle wird als separate Nachricht vor dem Embed gepingt (an-/abschaltbar).
- **Mehrsprachig** – Deutsch als Standard, pro Server umschaltbar (aktuell `de`, `en`).
- **Historie & Dashboard** – jeder Post wird gespeichert; im Dashboard einsehbar, mit Detailansicht und Löschfunktion.

## Installation

Voraussetzung: der Cog [`webcore`](../webcore/) ist installiert und eingerichtet.

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs changelog
[p]load changelog
```

`/changelog` ist ein Slash-Befehl. Falls die Slash-Befehle des Bots noch nicht synchronisiert sind, einmalig:

```
[p]slash enable changelog
[p]slash sync
```

## Schnellstart

```
[p]changelogset channel #server-news     # Ziel-Kanal festlegen
[p]changelogset roleadd @Discord-Team     # wer posten darf
[p]changelogset pingrole @Updates         # optionale Ping-Rolle
[p]changelogset ping on                    # Ping aktivieren
```

Danach im Server `/changelog` aufrufen, optional eine `kategorie` wählen, Formular ausfüllen, absenden – fertig. Alternativ lässt sich alles auch im **Dashboard** unter `/cogs/changelog` einstellen.

## Befehle

Posten (`/changelog`) – nur als Slash-Befehl, da ein Modal eine Interaction voraussetzt.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `/changelog [kategorie]` | Öffnet das Changelog-Formular; postet das Embed in den Ziel-Kanal. | Poster-Rollen / Admin |

Einstellungen (`changelogset`) – erfordern „Server verwalten" oder Admin.

| Befehl | Beschreibung |
|---|---|
| `[p]changelogset channel <#kanal>` | Ziel-Kanal für Changelogs festlegen |
| `[p]changelogset roleadd <rolle>` | Rolle hinzufügen, die posten darf |
| `[p]changelogset roleremove <rolle>` | Poster-Rolle entfernen |
| `[p]changelogset pingrole <rolle>` | Rolle festlegen, die vor dem Embed gepingt wird |
| `[p]changelogset ping <on\|off>` | Ping vor dem Embed an-/ausschalten |
| `[p]changelogset color <#hex>` | Embed-Farbe setzen (z. B. `#3DDC97`) |
| `[p]changelogset language <de\|en>` | Sprache setzen |
| `[p]changelogset catadd <emoji> <bezeichnung>` | Wählbare Kategorie hinzufügen |
| `[p]changelogset catremove <nummer>` | Kategorie per Nummer entfernen |
| `[p]changelogset cats` | Wählbare Kategorien anzeigen |
| `[p]changelogset show` | Aktuelle Einstellungen anzeigen |
| `[p]changelogset history [anzahl]` | Letzte Changelogs auflisten (Standard: 5) |

## Das Formular

Das Modal hat genau fünf Felder (Discord-Limit): **Titel** (Pflicht), **Neu**, **Geändert**, **Fixes** (je optional, mehrzeilig – ein Punkt pro Zeile) und **Hinweis** (optional). Mindestens eines der Felder *Neu/Geändert/Fixes* muss ausgefüllt sein, sonst postet der Bot nicht und meldet das nur der postenden Person (ephemer). Mehrzeilige Eingaben werden im Embed automatisch zu Bullet-Listen.

## Dashboard

Die Seite **Changelog** erscheint nach dem Laden automatisch im WebCore-Dashboard unter `/cogs/changelog`. Dort gibt es:

- ein Einstellungs-Formular (Ziel-Kanal, Sprache, Poster-Rollen, Ping-Rolle + Schalter, Embed-Farbe, wählbare Kategorien, Text-Overrides),
- eine **Historie-Tabelle** aller geposteten Changelogs (Datum, Kategorie, Titel, Kanal, Autor) mit Link „Zur Nachricht" und Löschfunktion,
- eine **Detailansicht** je Changelog mit allen Abschnitten,
- den Reiter **Launcher & Website** zum Freigeben der öffentlichen JSON-/RSS-Schnittstelle (siehe unten).

Die Server-Auswahl im Dashboard ist auf die Server beschränkt, die der eingeloggte User sehen darf.

## Öffentliche API für Launcher & Website

Die Changelogs eines Servers lassen sich ohne Login als **JSON** oder **RSS 2.0** abrufen – z. B. für
einen Spiele-Launcher oder die eigene Website.

**Einschalten:** Dashboard → **Changelog** → Reiter **Launcher & Website** → Schalter
„Changelogs öffentlich abrufbar machen“ → Speichern. Standard: **aus**. Dort stehen auch die fertigen
Adressen zum Kopieren und eine Beispiel-Antwort. Das Dashboard muss dafür **öffentlich erreichbar** sein
(Reverse-Proxy mit HTTPS, siehe [`webcore/README.md`](../webcore/README.md)).

| Adresse | Inhalt |
|---|---|
| `GET https://<dashboard>/api/public/changelog/<server-id>` | JSON |
| `GET https://<dashboard>/api/public/changelog/<server-id>/rss` | RSS 2.0 (`application/rss+xml`) |

Parameter (beide Formate): `limit` = Anzahl Einträge (1–50, Standard 10), `before` = Eintrags-ID
(z. B. `cl12`) – liefert nur ältere Einträge (Blättern: Wert aus `next_before` der vorigen Antwort).

- Ist die Freigabe aus oder gibt es den Server nicht, lautet die Antwort immer `404 {"error": "not_found"}`.
- Ausgegeben werden nur Titel, Inhalte, Kategorie, Datum, **Anzeigename** des Autors und der Link zur
  Discord-Nachricht – keine Nutzer-IDs.
- WebCore setzt `Access-Control-Allow-Origin: *` (Abruf direkt aus dem Browser möglich),
  `Cache-Control: public, max-age=60` und begrenzt auf 60 Abrufe pro Minute und IP.

Beispiel-Antwort:

```json
{
  "server": "Matters Community",
  "entries": [
    {
      "id": "cl12",
      "title": "Fahrzeug-Update",
      "category": {"emoji": "🚗", "label": "Fahrzeuge"},
      "sections": [
        {"key": "neu", "title": "Neu", "emoji": "🚗", "items": ["Neues Polizeiauto", "Tuning-Menü"]},
        {"key": "geaendert", "title": "Geändert", "emoji": "🔧", "items": ["Preise angepasst"]},
        {"key": "fixes", "title": "Fixes", "emoji": "🐛", "items": ["Absturz beim Einparken behoben"]}
      ],
      "note": "Server-Neustart um 20 Uhr",
      "created_at": "2026-09-25T18:00:00Z",
      "author": "Matters86",
      "url": "https://discord.com/channels/123456789012345678/234567890123456789/345678901234567890"
    }
  ],
  "next_before": "cl11"
}
```

`sections` enthält nur befüllte Bereiche (in der Sprache des Servers), `note` ist `null`, wenn kein
Hinweis gesetzt ist, `next_before` ist `null`, wenn es keine älteren Einträge gibt.

**curl:**

```bash
curl -s "https://dash.example.org/api/public/changelog/123456789012345678?limit=5"
curl -s "https://dash.example.org/api/public/changelog/123456789012345678/rss"
```

**JavaScript (Launcher/Website):**

```js
const BASE = "https://dash.example.org/api/public/changelog/123456789012345678";

async function loadChangelogs(limit = 10, before = null) {
  const url = new URL(BASE);
  url.searchParams.set("limit", limit);
  if (before) url.searchParams.set("before", before);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Changelog nicht verfügbar (${res.status})`);
  return res.json(); // { server, entries: [...], next_before }
}

const data = await loadChangelogs(5);
for (const e of data.entries) {
  console.log(e.created_at, e.title);
  for (const s of e.sections) console.log(` ${s.emoji} ${s.title}:`, s.items.join(" · "));
}
// Ältere Einträge: loadChangelogs(5, data.next_before)
```

Texte immer als **Text** einfügen (z. B. `textContent`), nicht als HTML – die Inhalte stammen von
Team-Mitgliedern und werden in JSON bewusst nicht HTML-escaped.

## Datenspeicherung

Pro Server werden die geposteten Changelogs gespeichert: Titel und Inhalte (Neu/Geändert/Fixes/Hinweis), die gewählte Kategorie, Kanal- und Nachrichten-ID sowie Anzeigename und Discord-ID der postenden Person (für die Historie). Einträge lassen sich im Dashboard löschen; beim Löschen wird auf Wunsch auch die Discord-Nachricht entfernt. Daten werden beim Entfernen des Cogs oder beim Verlassen des Servers gelöscht.
