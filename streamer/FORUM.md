# Streamer – nur aktive Twitch- und YouTube-Streams

Der Cog hält euren Stream-Kanal übersichtlich: Eingetragene Twitch- und YouTube-Kanäle werden
mit Titel, Vorschau und Stream-Link angekündigt. Ist der Stream offline, löscht der Bot seine
Meldung wieder. Andere Nachrichten bleiben erhalten.

Mit dem optionalen Titelfilter erscheinen beispielsweise nur Streams mit **DNP** im Titel.
Groß-/Kleinschreibung spielt keine Rolle. Der Filter wird auch bei Titeländerungen während
eines Streams geprüft. Ein leeres Feld zeigt alle Live-Streams der beobachteten Kanäle.

**Einrichtung:**

```text
[p]cog install red-cogs streamer
[p]load streamer
```

Im WebCore-Dashboard erscheint **Streamer**. Dort als Bot-Owner im Reiter **Zugang** den
Twitch-App-Zugang und/oder den YouTube-API-Key speichern. Danach unter **Einstellungen** den
Zielkanal und optional `DNP` als Titelfilter wählen. In der **Übersicht** die gewünschten Kanäle
hinzufügen. Teamrechte werden unter **Zugriff & Rollen → Streamer** vergeben.

Benötigte Bot-Rechte: **Kanal ansehen**, **Nachrichten senden**, **Links einbetten** und
**Nachrichtenverlauf lesen**. Gespeicherte Zugangsdaten werden niemals im Dashboard angezeigt.

**Prüfintervalle:** Twitch und bereits bekannte YouTube-Streams werden ungefähr minütlich
geprüft. Die Suche nach neuen YouTube-Streams läuft wegen der YouTube-Suchquote frühestens
alle 30 Minuten, bei vielen Kanälen seltener. Neue YouTube-Streams können daher verzögert
angezeigt werden. API-Störungen werden nicht als „offline“ behandelt.

| Befehl | Beschreibung | Rechte |
|---|---|---|
| `[p]streamer setup #kanal` | Zielkanal für Stream-Ankündigungen setzen. | Serververwaltung |
| `[p]streamer add twitch <name-oder-url>` | Twitch-Kanal hinzufügen. | Serververwaltung |
| `[p]streamer add youtube <@handle-kanal-id-oder-url>` | YouTube-Kanal hinzufügen. | Serververwaltung |
| `[p]streamer list` | Quellen mit ihren Schlüsseln auflisten. | Serververwaltung |
| `[p]streamer remove <quellenschlüssel>` | Quelle entfernen und ihre Meldungen bereinigen. | Serververwaltung |
| `[p]streamer filter [text]` | Titelfilter setzen; ohne Text ausschalten. | Serververwaltung |
| `[p]streamer check` | Aktuellen Status prüfen; YouTube-Suchgrenzen bleiben wirksam. | Serververwaltung |
| `[p]streamerset twitch <client-id> <client-secret>` | Twitch-Zugang botweit speichern. | Bot-Owner, ausschließlich per Direktnachricht |
| `[p]streamerset youtube <api-key>` | YouTube-Zugang botweit speichern. | Bot-Owner, ausschließlich per Direktnachricht |

`[p]` ersetzt ihr durch euren Bot-Präfix. Serververwaltung bedeutet Bot-Owner, Red-Admin oder
**Server verwalten**. Zugangsdaten vorzugsweise über das Dashboard eintragen; die beiden
`streamerset`-Befehle sind Textbefehle für Direktnachrichten an den Bot.

**Dashboard-Rechte:** Ansehen = Übersicht lesen; Bedienen = prüfen und Quellen pausieren/fortsetzen;
Bearbeiten = Quellen und Einstellungen verwalten. Zugangsdaten kann ausschließlich der Bot-Owner ändern.

Streamer ist eigenständig. Werden dieselben Twitch-Kanäle auch durch `twitchlive` angekündigt,
die Quelle dort oder in Streamer pausieren, um doppelte Meldungen zu vermeiden.

Anleitung und Einzelheiten zur YouTube-Quote stehen in `streamer/README.md`.
