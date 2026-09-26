# WebCore

Zentrales Web-Dashboard für Red-DiscordBot. Läuft **im Bot-Prozess** (aiohttp), bringt einen
Discord-OAuth2-Login mit und stellt anderen Cogs eine einfache API bereit, um eigene
Dashboard-Seiten zu registrieren. Neue Cogs erscheinen automatisch in der Navigation.

- **Rollen-Rechte:** Der Bot-Owner legt pro Server fest, welche Discord-Rolle welche Seite
  **ansehen** oder **bearbeiten** darf. Team-Mitglieder melden sich mit Discord an und sehen
  nur ihre freigegebenen Bereiche.
- **Globaler Server-Wechsler** in der Kopfzeile (die Auswahl bleibt beim Seitenwechsel erhalten).
- **Audit-Log:** jede Änderung über das Dashboard mit Nutzer, Server, Seite und Ergebnis – auf Wunsch
  zusätzlich als Embed in einem Discord-Kanal.
- **Mein Bereich (Mitglieder-Bereich):** pro Server zuschaltbar – normale Mitglieder melden sich an und
  sehen ausschließlich ihre persönlichen Seiten (z. B. eigene Tickets, eigenes Profil).
- **Öffentliche API** (`/api/public/…`) für Launcher/Websites – ohne Login, mit CORS, Cache und Rate-Limit.
- Einheitliche, übersichtliche Seiten (Reiter, Kennzahlen, Hilfetexte, Speicherleiste) über das
  gemeinsame UI-Kit; mobil bedienbar.
- Login-Seite, Nutzer-Menü mit Avatar und Rolle, Toast-Meldungen.

## Installation

```
[p]repo add red-cogs https://github.com/Matters86/red-cogs.git
[p]cog install red-cogs webcore
[p]load webcore
```

## Einrichtung

1. **Discord-Developer-Portal** → deine Application → Tab *OAuth2*.
   Unter *Redirects* deine Callback-URL eintragen, exakt so wie unten, z. B.
   `https://dashboard.deinedomain.de/callback` (oder `http://DEINE-IP:42100/callback` zum Testen).
   Für den Zugriff aus dem Internet siehe „Im Internet erreichbar machen“.
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
| `[p]webcore roleperm <rolle> <seite\|alle> <none\|view\|edit>` | Dashboard-Recht einer Rolle setzen (im Server ausführen) |
| `[p]webcore roles` | Dashboard-Rechte der Rollen dieses Servers anzeigen |
| `[p]webcore portal <on\|off>` | „Mein Bereich“ für Mitglieder dieses Servers ein-/ausschalten (im Server ausführen) |
| `[p]webcore auditchannel [#kanal]` | Audit-Log dieses Servers zusätzlich in einen Kanal posten; ohne Kanal = aus (im Server ausführen) |
| `[p]webcore settings` | Aktuelle Einstellungen anzeigen (ohne Secret) |

Alle `webcore`-Befehle sind dem Bot-Owner vorbehalten.

## Rollen-Rechte (Team-Zugang)

Im Dashboard unter **Verwaltung → Zugriff & Rollen** (nur Bot-Owner):

1. Oben rechts den Server wählen.
2. Unter „Rolle hinzufügen“ eine Discord-Rolle eintragen (Startwert *Ansehen* oder *Bearbeiten*).
3. In der Matrix pro Seite festlegen: **—** (kein Zugriff), **Ansehen** oder **Bearbeiten** – speichern.

| Stufe | Wirkung |
|---|---|
| — | Seite erscheint nicht in der Navigation, Aufruf wird abgelehnt (403). |
| Ansehen | Seite öffnet sich schreibgeschützt (Hinweis „Nur Ansicht“, alle Formulare gesperrt). |
| Bearbeiten | Alle Einstellungen und Aktionen dieser Seite – nur für **diesen Server**. |

- Hat ein Mitglied mehrere Rollen, gilt je Seite die höchste Stufe. Rechte gelten immer nur für
  den Server, auf dem die Rolle eingetragen ist.
- Die Rechte werden bei **jeder Anfrage live** aus den Discord-Rollen berechnet: Rolle entzogen
  = Zugriff sofort weg.
- **Schutz vor Selbst-Hochstufung:** Team-Mitglieder können Rollen nur dann automatisch
  vergeben lassen (Autorole-Beitrittsrollen/-Panels, Ticket-Inhaberrolle), wenn die Rolle
  **unter ihrer eigenen höchsten Rolle** liegt und **keine Moderations-/Verwaltungsrechte** hat.
- Botweite Einstellungen (z. B. Spec-Icons im Raidplaner, versteckte Befehle) und die Seiten
  „Zugriff & Rollen“ und „Audit-Log“ bleiben dem Owner vorbehalten.
- Wichtig: „Bearbeiten“ gibt **alle** Einstellungen einer Seite frei (bei Tickets z. B. auch die
  Admin-Rollen des Ticketsystems). Vergib es nur an Rollen, denen du das zutraust.

## Audit-Log

**Verwaltung → Audit-Log** zeigt jede speichernde Aktion im Dashboard: Zeit, Nutzer, Server,
Seite, Aktion und Ergebnis – auch abgelehnte Versuche ohne Bearbeitungsrecht. Aufbewahrt werden
die letzten 300 Einträge; Suche und Server-Filter sind eingebaut.

### Audit-Log nach Discord

Oben auf der Audit-Seite (Server oben rechts wählen) legt der Bot-Owner je Server einen
**Log-Kanal** fest – oder im Server mit `[p]webcore auditchannel #kanal` (ohne Kanal = aus).
Danach erscheint jeder Eintrag dieses Servers zusätzlich als Embed im Kanal: Zeit, Nutzer (als
Erwähnung, **ohne Ping**), Seite, Aktion und Ergebnis – grün für OK, rot für **abgelehnte Zugriffe**.
Das Posten läuft im Hintergrund; ist der Kanal weg oder fehlen dem Bot Rechte, wird das nur im
Bot-Log vermerkt, das Dashboard arbeitet normal weiter. Einträge ohne Server (z. B. botweite
Einstellungen) werden nicht gepostet.

## Mein Bereich (Mitglieder-Bereich)

Normale Server-Mitglieder ohne Team-Rechte können sich – wenn du es erlaubst – im Dashboard anmelden
und sehen dort **ausschließlich „Mein Bereich“**: eine Übersicht mit Kacheln und die
Mitglieder-Seiten, die Module anbieten (z. B. eigene Tickets). Team-Seiten, Übersicht mit
Bot-Kennzahlen, „Zugriff & Rollen“ und Audit-Log bleiben für sie gesperrt (403 bzw. Umleitung nach `/me`).

**Einschalten (Bot-Owner):** *Verwaltung → Zugriff & Rollen* → Server oben rechts wählen → Karte
„Mitglieder-Bereich“ → Schalter an → Speichern. Oder im Server: `[p]webcore portal on`.
Standard: auf allen Servern **aus**. Jede Änderung landet im Audit-Log.

- Zugang haben Mitglieder der Server, auf denen der Bereich an ist. Die Mitgliedschaft wird bei
  **jeder Anfrage live** geprüft – wer den Server verlässt, verliert den Zugang sofort.
- Wer auf mehreren freigeschalteten Servern ist, wechselt oben rechts; fremde Server lassen sich
  auch über `?guild=` nicht öffnen (der Versuch wird abgelehnt und protokolliert).
- **Team und Owner** sehen in der Navigation zusätzlich den Abschnitt „Mein Bereich“, sobald er auf
  einem ihrer Server aktiv ist, und können ihn auf ihren Team-Servern auch bei ausgeschaltetem
  Schalter als **Vorschau** öffnen (Button „Vorschau öffnen“ in der Karte).
- Schutz vor Missbrauch: höchstens **30 Speicher-Aktionen pro Minute** und Nutzer (danach Meldung
  „Zu viele Anfragen“, HTTP 429). Aktionen von Mitgliedern landen **nicht** im Audit-Log (sonst
  würde es geflutet) – abgelehnte Zugriffe (fremder Server, ungültiges Token, Rate-Limit) schon.
- Discord-Login mit Scope `identify` genügt; das Members-Intent wird empfohlen (sonst prüft WebCore
  die Mitgliedschaft per API-Abfrage mit 5 Minuten Cache).

## Sicherheit

- **Rollen-Rechte** (siehe oben) gelten in jedem Modus zusätzlich.
- **Zugriffsmodi** (per `[p]webcore access` umschaltbar):
  - `owner` (Standard): nur Bot-Owner und Co-Owner.
  - `admin`: zusätzlich Discord-Admins – aber **eingeschränkte Sicht**: sie sehen nur die
    Server, in denen sie Administrator sind, und keine Bot-Infrastruktur (RAM/CPU, Versionen,
    serverübergreifende Zahlen). Erfordert das **Members-Intent**, damit Mitglieder erkannt werden.
  - `allowlist`: zusätzlich die per `[p]webcore allow` freigegebenen User – mit **voller Sicht**.
- Owner und Allowlist-User haben volle Sicht (alle Server + Infrastruktur).
- Login-Sitzungen laufen nach 7 Tagen ab. Jede Anfrage prüft die Rechte neu.
- Jede Antwort trägt Sicherheits-Header (kein Einbetten in fremde Seiten, `nosniff`,
  `Referrer-Policy`, `no-store` für Seiten). HSTS setzt der Reverse-Proxy.
- Ist die `redirect_uri` eine `https://`-Adresse, wird das Sitzungscookie nur noch über HTTPS
  gesendet (`Secure`).
- `GET /healthz` antwortet ohne Login mit `ok` – für Docker-Healthchecks oder Uptime-Monitore.
- Den Port **nie direkt** ins Internet freigeben, sondern immer über einen Reverse-Proxy mit HTTPS
  (siehe nächster Abschnitt).

## Im Internet erreichbar machen (Synology NAS mit Docker)

Ziel: `https://<dein-ddns-name>:<port>` → Synology-Reverse-Proxy (HTTPS, Zertifikat) →
Bot-Container Port 42100 (HTTP, nur im Heimnetz).

```
Internet ──HTTPS :4445──► Router ──► NAS: DSM-Reverse-Proxy ──HTTP──► localhost:42100 (Red + WebCore)
```

Beispielwerte unten: DDNS-Name `matters86launcher.synology.me`, freier Port `4445`
(4443 ist schon für den Launcher belegt).

1. **Container-Port freigeben** – *Container Manager → Container → (Red-Bot) → Bearbeiten →
   Port-Einstellungen*: lokaler Port `42100` → Container-Port `42100` (TCP). Bei `docker compose`:
   `ports: ["42100:42100"]`. Läuft der Container im Netzwerkmodus `host`, entfällt das.
   WebCore muss im Container auf `0.0.0.0` lauschen (Standard, prüfen mit `[p]webcore settings`).
2. **Im Heimnetz testen:** `http://<NAS-IP>:42100/healthz` muss `ok` zeigen.
3. **Reverse-Proxy anlegen** – *Systemsteuerung → Anmeldeportal → Erweitert → Reverse Proxy →
   Erstellen*:
   - Quelle: Protokoll `HTTPS`, Hostname `matters86launcher.synology.me`, Port `4445`
     (optional „HSTS aktivieren“ – gilt dann für alle HTTPS-Dienste dieses Hostnamens).
   - Ziel: Protokoll `HTTP`, Hostname `localhost`, Port `42100`.
4. **Zertifikat zuweisen** – *Systemsteuerung → Sicherheit → Zertifikat → Einstellungen*: beim
   neuen Reverse-Proxy-Eintrag das Zertifikat für `matters86launcher.synology.me` auswählen
   (dasselbe wie für den Launcher).
5. **Router-Portweiterleitung:** extern TCP `4445` → NAS-IP Port `4445` (genau wie 4443 für den
   Launcher). Port `42100` **nicht** weiterleiten. Ist die DSM-Firewall aktiv, `4445` erlauben.
6. **Discord-Developer-Portal** → Application → *OAuth2 → Redirects*:
   `https://matters86launcher.synology.me:4445/callback` hinzufügen.
7. **Bot umstellen** (Nachricht mit dem Secret wird automatisch gelöscht):
   ```
   [p]webcore oauth <client_id> <client_secret> https://matters86launcher.synology.me:4445/callback
   [p]reload webcore
   ```
8. **Von außen testen** (Handy im Mobilfunknetz, nicht im WLAN):
   `https://matters86launcher.synology.me:4445` → Login mit Discord.
9. **Zugriff vergeben:** Grundmodus `owner` lassen und dem Team über *Verwaltung → Zugriff & Rollen*
   gezielt Seiten freigeben.

Hinweise:
- Nach Schritt 7 funktioniert der Login nur noch über die HTTPS-Adresse (Cookie `Secure`). Für
  lokale Tests ohne HTTPS vorübergehend wieder eine `http://…/callback`-Adresse setzen.
- Statt eines eigenen Ports geht auch eine Subdomain wie `dashboard.matters86launcher.synology.me`
  auf Port 443, wenn das Zertifikat die Subdomain (Wildcard) abdeckt und 443 weitergeleitet ist.
- Fehlerbild „Ungültige redirect_uri“ bei Discord: Adresse in Portal und Bot müssen **exakt**
  gleich sein (inkl. Port und `/callback`).

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

## UI-Kit für Cog-Seiten (`webcore/ui.py`)

Alle Dashboard-Seiten nutzen dieselben Bausteine – dadurch sehen sie gleich aus und bekommen
Reiter, Speicherleiste, Chip-Auswahl, Bestätigungsdialoge, Tabellensuche und die Handy-Ansicht
automatisch. Zugriff im Handler: `ui = request.app["webcore"].ui`.

| Baustein | Zweck |
|---|---|
| `ui.hero(icon, "", text)` | Kopfzeile der Seite: Icon + ein Satz, was die Seite macht |
| `ui.stats([(label, wert, icon, hinweis, ton)])` | Kennzahlen-Kacheln (`ton`: ok/warn/bad/info) |
| `ui.tab(key, titel, icon, inhalt, count=n)` | Reiter; mehrere hintereinander ergeben die Reiterleiste |
| `ui.card(titel, inhalt, desc=…, icon=…, actions=…)` | Karte mit Überschrift und Kurzbeschreibung |
| `ui.callout(text, tone=…)`, `ui.empty(icon, titel, text)` | Hinweisbox, leerer Zustand |
| `ui.form(action, inhalt, csrf=…, hidden={…}, savebar=True)` | Formular inkl. CSRF; `savebar` zeigt bei Änderungen „Speichern/Verwerfen“; `confirm="…"` fragt vor dem Absenden; `enctype=` für Uploads |
| `ui.grid(ui.field(label, control, help=…), cols=2)` | Formularraster mit Hilfetexten |
| `ui.switch`, `ui.switches(...)`, `ui.text_input`, `ui.number(…, unit="Sek.")`, `ui.textarea`, `ui.color_input` | Eingabefelder |
| `ui.select(name, [(wert, label[, farbe])], selected, multiple=True)` | Auswahl; `multiple` wird zur durchsuchbaren Chip-Auswahl |
| `ui.button(label, icon=…, kind="danger", confirm="Wirklich?")` | Buttons, optional mit Bestätigungsdialog |
| `ui.table(köpfe, [ui.row(...)], search=True)` | Tabelle mit Suche; auf dem Handy automatisch als Karten |

Regeln: Titel im Hero leer lassen (die Kopfzeile zeigt den Seitennamen), ein Einstellungsformular
darf mehrere Reiter umschließen (ein Speichern sendet alles), Werte in eigenem Markup mit
`html.escape` absichern. Ein kurzes Vorbild ist `example/example.py`, ein großes `tickets/dashboard.py`.

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

`visible_guilds(request)` liefert für Owner/Allowlist-User alle Server, sonst nur die Server, auf
denen der User für **diese Seite** mindestens *Ansehen* hat – bei **POST** mindestens
*Bearbeiten*. Wer die Ziel-Guild eines Formulars gegen diese Liste prüft (so machen es alle Cogs
im Repo), bekommt die Rollen-Rechte damit automatisch. Zusätzlich lehnt WebCore POSTs zentral ab,
wenn das Feld `guild`/`guild_id` auf einen Server ohne Bearbeiten-Recht zeigt.

### Weitere Helfer für Cogs

| Aufruf | Zweck |
|---|---|
| `await webcore.page_level(request, guild)` | Stufe des Users auf dieser Seite: 0 = kein Zugriff, 1 = Ansehen, 2 = Bearbeiten |
| `await webcore.has_full_scope(request)` | Owner/Allowlist? – für botweite Einstellungen |
| `await webcore.can_grant_role(request, guild, role)` | Darf der User diese Rolle automatisch vergeben lassen? (Schutz vor Selbst-Hochstufung) |

**Server-Auswahl:** WebCore hängt beim Öffnen einer Cog-Seite immer `?guild=<id>` an (zuletzt
gewählter Server). Eine Cog-Seite liest einfach `request.query.get("guild")` und braucht kein
eigenes Server-Dropdown mehr – solange `request.get("wc_switcher")` gesetzt ist, zeigt WebCore
den Wechsler in der Kopfzeile.

**Meldungen:** `?ok=<Text>` bzw. `?err=<Text>` in der Weiterleitung nach einem POST zeigt WebCore
als Toast an (Hinweisbalken mit einer Klasse `…-flash` werden dann ausgeblendet).

## Für Cog-Entwickler: Mitglieder-Seiten („Mein Bereich“)

```python
def _register_dashboard(self, webcore):
    webcore.register_page(owner=self, slug="tickets", name="Tickets", handler=self.dashboard_page)
    webcore.register_member_page(
        owner=self, slug="tickets", name="Meine Tickets", handler=self.member_page,
        icon="bi-ticket-perforated", description="Deine offenen und geschlossenen Tickets.",
    )

async def member_page(self, request):
    guild = request["wc_member_guild"]      # discord.Guild (gewählter Server)
    member = request["wc_member"]           # discord.Member des angemeldeten Users auf diesem Server
    csrf = request["webcore_csrf"]
    ui = request.app["webcore"].ui
    if request.method == "POST":            # CSRF + Rate-Limit schon geprüft
        form = await request.post()
        ...                                  # nur Daten von `member` ändern!
        return {"redirect": f"/me/tickets?guild={guild.id}&ok=Gespeichert"}
    return {"title": "Meine Tickets", "content": ui.card("Offen", "…")}
```

| API | Zweck |
|---|---|
| `register_member_page(owner, slug, name, handler, icon="bi-grid", description="")` | Seite unter `/me/<slug>` (GET + POST); Kachel auf `/me` mit Icon, Name, Beschreibung |
| `request["wc_member_guild"]` / `request["wc_member"]` / `request["webcore_csrf"]` | vor dem Handler gesetzt: Server, eigenes `discord.Member`, CSRF-Token |
| `await webcore.portal_guilds(request)` | Server, die der User in „Mein Bereich“ wählen darf |
| `await webcore.member_context(request)` | `(guild, member)` oder `None` (auch außerhalb von `/me/<slug>` nutzbar) |
| `unregister_owner(owner)` | entfernt auch Mitglieder-Seiten und öffentliche APIs |

- Handler-Rückgabe wie bei Cog-Seiten: `{"title", "content"}`, `{"redirect": url}` oder eine `web.Response`.
- Server-Auswahl: `?guild=<id>` (WebCore hängt ihn an und zeigt den Wechsler). Bei POST zählt das Feld
  `guild`/`guild_id`, sonst `?guild=` – immer gegen die erlaubten Server geprüft.
- Jedes Formular sendet `csrf_token` mit (z. B. über `ui.form(..., csrf=request["webcore_csrf"])`).
- Fehler im Handler zeigen Mitgliedern nur eine neutrale Meldung (Details im Bot-Log).

**Regeln (Pflicht):**
1. **Nur eigene Daten** des Mitglieds anzeigen und ändern – immer über `request["wc_member"].id` filtern,
   nie über IDs aus Formular/URL (sonst kann man fremde Tickets/Profile abrufen).
2. **Jede Aktion serverseitig prüfen** wie der entsprechende Discord-Button (Cooldowns, Limits,
   „darf dieses Mitglied das überhaupt“ – z. B. Ticket nur schließen, wenn es sein eigenes ist).
3. Keine Team-Informationen (interne Notizen, Logs, andere Mitglieder) ausgeben; Werte mit `html.escape`.
4. `visible_guilds`/`page_level` gelten hier nicht (liefern im Mitglieder-Bereich `[]` bzw. 0) –
   `portal_guilds`/`member_context` verwenden.

## Für Cog-Entwickler: öffentliche API (Launcher/Websites)

```python
from aiohttp import web

def _register_dashboard(self, webcore):
    webcore.register_public_api(owner=self, slug="serverstatus", handler=self.public_status)

async def public_status(self, request):
    tail = request.match_info.get("tail", "")   # /api/public/serverstatus/<tail>
    return web.json_response({"online": 42, "tail": tail})
```

- Erreichbar unter `GET /api/public/<slug>` und `GET /api/public/<slug>/<beliebiger/rest>` –
  **ohne Login und ohne Sitzung** (es wird kein Cookie gelesen oder gesetzt).
- WebCore setzt `Access-Control-Allow-Origin: *` (nur GET/OPTIONS, Preflight wird beantwortet) und
  `Cache-Control: public, max-age=60` (ein eigener `Cache-Control`-Header des Handlers hat Vorrang).
- Rate-Limit: **60 Anfragen pro Minute und IP** (danach `429` mit `Retry-After`).
- Fehler im Handler → `500` mit `{"error": "internal_error"}` (kein Stacktrace, Details im Bot-Log);
  unbekannter slug → `404` `{"error": "not_found"}`. `web.HTTPNotFound()` usw. im Handler werden als
  JSON-Fehler mit passendem Status ausgeliefert.
- Nur **öffentliche** Daten ausliefern (keine Nutzer-IDs, Tokens, internen Notizen).
- Hinter einem Reverse-Proxy: Die Client-IP für das Rate-Limit kommt aus `X-Forwarded-For`, aber nur,
  wenn die Verbindung von `127.0.0.1`/`::1` oder aus einem privaten Netz (z. B. Docker, Synology-Proxy)
  kommt; sonst zählt die direkte Gegenstelle (gefälschte Header aus dem Internet wirken nicht).
