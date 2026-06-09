# WebCore

Zentrales Web-Dashboard für Red-DiscordBot. Läuft **im Bot-Prozess** (aiohttp), bringt einen
Discord-OAuth2-Login mit und stellt anderen Cogs eine einfache API bereit, um eigene
Dashboard-Seiten zu registrieren. Neue Cogs erscheinen automatisch in der Navigation.

## Installation

```
[p]repo add red-cogs <github-url>
[p]cog install red-cogs webcore
[p]load webcore
```

## Einrichtung

1. **Discord-Developer-Portal** → deine Application → Tab *OAuth2*.
   Unter *Redirects* deine Callback-URL eintragen, exakt so wie unten, z. B.
   `https://dashboard.deinedomain.de/callback` (oder `http://DEINE-IP:42100/callback` zum Testen).
2. Client-ID und Client-Secret kopieren und im Bot setzen:
   ```
   [p]webcore oauth <client_id> <client_secret> <redirect_uri>
   ```
   (Die Nachricht mit dem Secret wird automatisch gelöscht.)
3. Optional Port/Host anpassen, danach neu laden:
   ```
   [p]webcore port 42100
   [p]reload webcore
   ```
4. Dashboard im Browser öffnen: die in Schritt 1 genutzte Basis-URL.

## Befehle

| Befehl | Beschreibung |
|---|---|
| `[p]webcore oauth <id> <secret> <redirect>` | OAuth2-Daten setzen |
| `[p]webcore port <port>` | Webserver-Port setzen (Standard 42100) |
| `[p]webcore host <host>` | Bind-Host setzen (Standard 0.0.0.0) |
| `[p]webcore access <owner|admin|allowlist>` | Zugriffsmodus setzen |
| `[p]webcore allow <user>` | User freigeben (volle Sicht) |
| `[p]webcore deny <user>` | Freigabe entfernen |
| `[p]webcore settings` | Aktuelle Einstellungen anzeigen (ohne Secret) |

## Sicherheit

- **Zugriffsmodi** (per `[p]webcore access` umschaltbar):
  - `owner` (Standard): nur Bot-Owner und Co-Owner.
  - `admin`: zusätzlich Discord-Admins – aber **eingeschränkte Sicht**: sie sehen nur die
    Server, in denen sie Administrator sind, und keine Bot-Infrastruktur (RAM/CPU, Versionen,
    serverübergreifende Zahlen). Erfordert das **Members-Intent**, damit Mitglieder erkannt werden.
  - `allowlist`: zusätzlich die per `[p]webcore allow` freigegebenen User – mit **voller Sicht**.
- Owner und Allowlist-User haben volle Sicht (alle Server + Infrastruktur).
- Empfehlung: den Webserver hinter einen Reverse-Proxy mit HTTPS legen (z. B. Caddy/Nginx),
  statt den Port direkt offen ins Internet zu stellen.

## Für Cog-Entwickler: eigene Seite registrieren

```python
class MeinCog(commands.Cog):
    async def cog_load(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:                 # falls WebCore schon läuft
            self._register_dashboard(webcore)

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):  # falls WebCore später lädt
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="meincog",
            name="Mein Cog",
            icon="bi-stars",
            handler=self.dashboard_page,
        )

    async def dashboard_page(self, request):
        return {"title": "Mein Cog", "content": "<div class='card-x'>Hallo Welt</div>"}
```

Der `handler` bekommt das aiohttp-`request` und gibt ein Dict mit `title` und `content`
(HTML-String) zurück. Der Inhalt wird in das gemeinsame Layout eingebettet – nutzbare
CSS-Klassen u. a.: `card-x`, `table`, `stat`, `stat-label`, `mono`, `btn-accent`.

## Einstellungen über das Dashboard ändern (Formulare, POST + CSRF)

Seiten dürfen nicht nur anzeigen, sondern auch schreiben. Jede Cog-Seite ist sowohl per
**GET** als auch per **POST** unter `/cogs/<slug>` erreichbar – derselbe `handler` bekommt
beide Anfragen, unterschieden über `request.method`.

WebCore legt pro Sitzung ein **CSRF-Token** an und stellt es dem Handler unter
`request["webcore_csrf"]` bereit. Jedes Formular muss dieses Token als verstecktes Feld
`csrf_token` mitsenden – WebCore prüft es bei jedem POST zentral und lehnt fehlende/falsche
Token mit HTTP 400 ab. Nach erfolgreichem Schreiben sollte der Handler per
`return {"redirect": "/cogs/<slug>"}` umleiten (Post/Redirect/Get), damit ein Neuladen die
Aktion nicht erneut auslöst.

```python
async def dashboard_page(self, request):
    csrf = request.get("webcore_csrf", "")

    if request.method == "POST":
        form = await request.post()          # CSRF wurde bereits von WebCore geprüft
        await self.config.guild_from_id(int(form["guild_id"])).note.set(form.get("note", ""))
        return {"redirect": "/cogs/meincog?ok=1"}

    content = (
        "<form method='post' action='/cogs/meincog' class='card-x'>"
        f"<input type='hidden' name='csrf_token' value='{csrf}'>"
        "<input name='note' class='form-control'>"
        "<button class='btn-accent' type='submit'>Speichern</button>"
        "</form>"
    )
    return {"title": "Mein Cog", "content": content}
```

Nutzereingaben aus Formularen immer mit `html.escape(...)` ausgeben und Zahlen/Werte
serverseitig validieren (z. B. Channel-IDs gegen die echten Guild-Objekte prüfen).

### Sicht pro User einschränken (`visible_guilds`)

Wenn der Zugriffsmodus `admin` aktiv ist, dürfen auch Server-Admins ins Dashboard – sie
sollen aber **nur ihre eigenen Server** sehen. Damit deine Seite das respektiert, hol dir die
erlaubten Server über WebCore statt über `self.bot.guilds`:

```python
async def dashboard_page(self, request):
    webcore = self.bot.get_cog("WebCore")
    guilds = await webcore.visible_guilds(request)   # Owner/Allowlist -> alle, Admin -> nur eigene
    # Server-Dropdown / Daten nur aus `guilds` aufbauen
    ...
```

`visible_guilds(request)` liefert für Owner/Allowlist-User alle Server, für Admin-Modus-User nur
die, in denen sie Administrator sind. So bleibt die serverbezogene Datentrennung gewahrt.
