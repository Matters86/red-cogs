"""WebCore-Harness für Bot-Status, Fehlerprotokoll und Sichern & Wiederherstellen.

Baut auf wc_harness.py auf (unverändert importiert) und ergänzt:
* ``bot.cogs`` = die registrierten Cogs (wie bei Red), damit der Bot-Status sie auflistet
* Demo-Cog „WsDemo“ mit echter Red-``Config`` inkl. Secret-Schlüsseln (Server + botweit),
  einer Dashboard-Seite, einer Mitglieder-Seite und einer öffentlichen API
* das Fehlerprotokoll (Handler am Logger ``red``) ist installiert, WebCore-client_secret gesetzt

Start: python tests/ws_harness.py [port]   (ohne Port: freier Port)
"""
import logging

from redbot.core import Config, commands

import wc_harness as H

CLIENT_SECRET = "wsGeheimesClientSecret123"
DEMO_IDENTIFIER = 5550172839461


class WsDemo(commands.Cog):
    """Demo-Cog nur für Tests (Server- und botweite Einstellungen mit Secrets)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=DEMO_IDENTIFIER, force_registration=True)
        self.config.register_guild(greeting="Hallo", enabled=False, limit=5, channels=[], options={"color": "blue"},
                                   channel_id=None, api_token=None)
        self.config.register_global(public_name="Demo", client_secret=None, nested={"mode": "a", "password": None})

    def _register_dashboard(self, wc):
        wc.register_page(owner=self, slug="wsdemo", name="WS-Demo", icon="bi-stars", handler=self.page)
        wc.register_member_page(self, "wsdemo", "WS-Demo", self.member_page, icon="bi-stars", description="Demo")
        wc.register_public_api(self, "wsdemo", self.api)

    async def page(self, request):
        return {"title": "WS-Demo", "content": "<div class='card-x'>Demo</div>"}

    async def member_page(self, request):
        return {"title": "WS-Demo", "content": "<div class='card-x'>Demo</div>"}

    async def api(self, request):
        return {"ok": True}

    @commands.command()
    async def wsdemo(self, ctx):
        """Demo-Befehl."""


async def make_app():
    wc, bot, app = await H.make_app()
    demo = WsDemo(bot)
    bot._cogs["WsDemo"] = demo
    demo._register_dashboard(wc)
    bot.cogs = bot._cogs
    await wc.config.client_secret.set(CLIENT_SECRET)
    wc._install_error_log()
    await wc._refresh_known_secrets()
    return wc, bot, app


if __name__ == "__main__":
    async def _make_with_samples():
        wc, bot, app = await make_app()
        lg = logging.getLogger("red.red-cogs.wsdemo")
        lg.warning("Beispiel-Warnung mit token=abc123456 und <b>HTML</b>")
        try:
            raise RuntimeError(f"Verbindung fehlgeschlagen: Authorization: Bearer xyz987654 ({CLIENT_SECRET})")
        except RuntimeError:
            lg.exception("Beispiel-Fehler beim Abruf")
        logging.getLogger("red.tickets").error("Ticket-Kanal nicht gefunden")
        return wc, bot, app
    H.main(_make_with_samples)
