from redbot.core import Config, commands
from redbot.core.bot import Red


class Example(commands.Cog):
    """Beispiel-Cog als Vorlage: ein Befehl plus eine eigene Dashboard-Seite."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=290117450912, force_registration=True)
        self.config.register_guild(note="")

    # ----------------------------------------------------------------- #
    #  Dashboard-Anbindung
    # ----------------------------------------------------------------- #
    async def cog_load(self):
        # Falls WebCore bereits läuft, sofort registrieren.
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            self._register_dashboard(webcore)

    async def cog_unload(self):
        webcore = self.bot.get_cog("WebCore")
        if webcore is not None:
            webcore.unregister_owner(self)

    @commands.Cog.listener()
    async def on_webcore_ready(self, webcore):
        # Falls WebCore NACH diesem Cog geladen wird.
        self._register_dashboard(webcore)

    def _register_dashboard(self, webcore):
        webcore.register_page(
            owner=self,
            slug="example",
            name="Example",
            icon="bi-stars",
            handler=self.dashboard_page,
            # Rechte-Stufe „Bedienen“ (Tagesgeschäft): Die Notiz hier ist eine Einstellung, darum braucht jeder
            # POST „Bearbeiten“. Hat dein Cog Aktionen an EINZELNEN Einträgen (z. B. Event schließen, Nachricht
            # neu posten, Eintrag löschen), markiere deren Formulare als Tagesgeschäft – Werte des POST-Feldes
            # ``form`` (falls vorhanden, sonst ``action``); der Handler muss nach genau diesem Feld verzweigen:
            #   operate_forms={"event_action", "repost"},
            # Im Markup: ``ui.form(..., hidden={"form": "event_action", ...})`` oder ``ui.form(..., operate=True)``.
            # NIE Tagesgeschäft: Einstellungen, Texte, Rollen-Zuordnung, Massenaktionen (siehe webcore/README.md).
            # Für ältere WebCore-Versionen: nur übergeben, wenn ``hasattr(webcore, "OPERATE")``.
        )

    async def dashboard_page(self, request):
        """Vorlage für neue Cogs – das empfohlene Muster in kurz:

        * Server NUR über ``webcore.visible_guilds(request)`` auflösen (nie ``self.bot.guilds``).
          Die Liste ist seitenbewusst: GET = Server mit „Ansehen“, POST = mit „Bearbeiten“ bzw. mit
          „Bedienen“ bei Tagesgeschäft-Formularen (``operate_forms``, Rollen-Rechte aus „Zugriff & Rollen“).
          Für die Oberfläche: ``await webcore.can_edit(request, guild)`` / ``can_operate(...)``.
        * Den gewählten Server liest man aus ``?guild=`` – WebCore setzt ihn automatisch und
          zeigt den globalen Server-Wechsler; ein eigenes Dropdown ist nicht nötig.
        * Jedes Formular: ``csrf_token`` + ``guild`` mitsenden, danach PRG mit ``?ok=<Text>``
          (WebCore zeigt den Text als Hinweis-Toast).
        * Markup nur über den UI-Baukasten ``webcore.ui`` – er escaped alle Parameter,
          bringt Reiter, Karten, Schalter & Speicherleiste mit; kein eigenes CSS nötig.
        """
        webcore = request.app["webcore"]
        ui = webcore.ui
        guilds = await webcore.visible_guilds(request)
        by_id = {g.id: g for g in guilds}

        # --- Speichern (POST) -> danach Redirect (Post/Redirect/Get) ---
        if request.method == "POST":
            form = await request.post()
            raw = form.get("guild") or ""
            guild = by_id.get(int(raw)) if raw.isdigit() else None
            if guild is None:  # kein Bearbeiten-Recht auf diesem Server (oder unbekannt)
                return {"redirect": "/cogs/example?ok=Server+nicht+gefunden"}
            await self.config.guild(guild).note.set((form.get("note") or "").strip()[:500])
            return {"redirect": f"/cogs/example?guild={guild.id}&ok=Notiz+gespeichert"}

        # --- Anzeigen (GET) ---
        raw = request.query.get("guild") or ""
        guild = by_id.get(int(raw)) if raw.isdigit() else (guilds[0] if guilds else None)
        if guild is None:
            return {"title": "Example", "content": ui.card(body=ui.empty("bi-hdd-network", "Keine Server verfügbar."))}
        note = await self.config.guild(guild).note()

        # Kopf: Symbol + kurzer Satz (Titel leer – die Kopfzeile zeigt den Seitennamen schon).
        # ``text`` ist HTML -> eigene Werte mit ``ui.esc`` escapen.
        head = ui.hero("bi-stars", "", f"Beispielseite für <b>{ui.esc(guild.name)}</b> – Vorlage für eigene Cogs.")
        # Kennzahlen: (Label, Wert, Icon, Hinweis, Ton ok/warn/bad/info)
        stats = ui.stats([
            ("Mitglieder", guild.member_count, "bi-people", None, None),
            ("Notiz", "gesetzt" if note else "leer", "bi-sticky", None, "ok" if note else None),
        ])
        # Formular: CSRF-Token setzt ui.form selbst, weitere Felder über ``hidden``.
        # ``savebar=True`` blendet bei Änderungen die Leiste „Ungespeicherte Änderungen“ ein.
        # Weitere Bausteine für ui.grid(...):
        #   ui.field("Aktiv", ui.switch("enabled", "Modul aktiv", conf["enabled"]))  # angehakt = Feld gesendet
        #   ui.field("Limit", ui.number("limit", conf["limit"], min=1, max=10, unit="pro Tag"))
        #   ui.field("Kanal", ui.select("channel", [(c.id, f"#{c.name}") for c in guild.text_channels],
        #                               conf["channel"], none_label="— keiner —"))
        #   ui.select(..., multiple=True) wird automatisch zur Chip-Auswahl mit Suche.
        # Mehrere Bereiche? Jede ``ui.tab(key, titel, icon, inhalt)``-Sektion wird zu einem Reiter.
        form = ui.form(
            "/cogs/example",
            ui.grid(
                ui.field("Notiz", ui.text_input("note", note or "", placeholder="Notiz für diesen Server",
                                                attrs={"maxlength": 500}),
                         help="Wird mit <code>[p]example note</code> angezeigt (max. 500 Zeichen).", wide=True),
            ) + ui.save_row(),
            csrf=request.get("webcore_csrf", ""), hidden={"guild": guild.id}, savebar=True,
        )
        card = ui.card("Server-Notiz", form, icon="bi-sticky", desc="Eine kurze Notiz, die pro Server gespeichert wird.")
        return {"title": "Example", "content": head + stats + card}

    # ----------------------------------------------------------------- #
    #  Befehle (hybrid = Text + Slash)
    # ----------------------------------------------------------------- #
    @commands.hybrid_group(name="example")
    async def example(self, ctx: commands.Context):
        """Beispiel-Befehle."""

    @example.command(name="hello")
    async def example_hello(self, ctx: commands.Context):
        """Sagt Hallo."""
        await ctx.send("Hallo! 👋")

    @example.command(name="note")
    @commands.guild_only()
    async def example_note(self, ctx: commands.Context):
        """Zeigt die Notiz dieses Servers."""
        note = await self.config.guild(ctx.guild).note()
        await ctx.send(note or "Noch keine Notiz gesetzt.")

    @example.command(name="setnote")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def example_setnote(self, ctx: commands.Context, *, text: str):
        """Setzt eine Notiz für diesen Server."""
        await self.config.guild(ctx.guild).note.set(text)
        await ctx.send("Notiz gespeichert.")
