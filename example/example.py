import html as html_lib

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
        )

    async def dashboard_page(self, request):
        """Vorlage für neue Cogs – das empfohlene Muster in kurz:

        * Server NUR über ``webcore.visible_guilds(request)`` auflösen (nie ``self.bot.guilds``).
          Die Liste ist seitenbewusst: GET = Server mit „Ansehen“, POST = mit „Bearbeiten“
          (Rollen-Rechte aus „Zugriff & Rollen“).
        * Den gewählten Server liest man aus ``?guild=`` – WebCore setzt ihn automatisch und
          zeigt den globalen Server-Wechsler; ein eigenes Dropdown ist nicht nötig.
        * Jedes Formular: ``csrf_token`` + ``guild`` mitsenden, danach PRG mit ``?ok=<Text>``.
        """
        webcore = request.app.get("webcore")
        guilds = await webcore.visible_guilds(request) if webcore is not None else []
        by_id = {g.id: g for g in guilds}

        if request.method == "POST":
            form = await request.post()
            raw = form.get("guild") or ""
            guild = by_id.get(int(raw)) if raw.isdigit() else None
            if guild is None:  # kein Bearbeiten-Recht auf diesem Server (oder unbekannt)
                return {"redirect": "/cogs/example?ok=Server+nicht+gefunden"}
            await self.config.guild(guild).note.set((form.get("note") or "").strip()[:500])
            return {"redirect": f"/cogs/example?guild={guild.id}&ok=Notiz+gespeichert"}

        raw = request.query.get("guild") or ""
        guild = by_id.get(int(raw)) if raw.isdigit() else (guilds[0] if guilds else None)
        if guild is None:
            return {"title": "Example", "content": "<div class='card-x'>Keine Server verfügbar.</div>"}
        note = await self.config.guild(guild).note()
        csrf = html_lib.escape(request.get("webcore_csrf", ""))
        content = (
            "<div class='card-x'>"
            f"<div class='section-title'>{html_lib.escape(guild.name)}</div>"
            f"<p style='color:var(--muted)'>Mitglieder: <span class='mono'>{guild.member_count}</span></p>"
            "<form method='post' action='/cogs/example' style='display:flex;gap:10px;flex-wrap:wrap'>"
            f"<input type='hidden' name='csrf_token' value='{csrf}'>"
            f"<input type='hidden' name='guild' value='{guild.id}'>"
            f"<input name='note' class='form-control' style='max-width:420px' value='{html_lib.escape(note or '')}' "
            "placeholder='Notiz für diesen Server'>"
            "<button class='btn-accent' type='submit'>Speichern</button>"
            "</form></div>"
        )
        return {"title": "Example", "content": content}

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
