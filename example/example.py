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
        rows = []
        for guild in sorted(self.bot.guilds, key=lambda g: g.name.lower()):
            note = await self.config.guild(guild).note()
            note_cell = html_lib.escape(note) if note else "<span style='color:var(--muted)'>—</span>"
            rows.append(
                "<tr>"
                f"<td>{html_lib.escape(guild.name)}</td>"
                f"<td class='mono'>{guild.member_count}</td>"
                f"<td>{note_cell}</td>"
                "</tr>"
            )
        body = "".join(rows) or "<tr><td colspan='3' style='color:var(--muted)'>Keine Server.</td></tr>"
        content = (
            "<div class='card-x'>"
            "<table class='table'>"
            "<thead><tr><th>Server</th><th>Mitglieder</th><th>Notiz</th></tr></thead>"
            f"<tbody>{body}</tbody>"
            "</table></div>"
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
