from .serverstats import ServerStats

__red_end_user_data_statement__ = (
    "Dieser Cog speichert keine personenbezogenen Daten – nur anonyme Tages-Summen je Kanal "
    "(Beitritte, Abgänge, Mitgliederzahl, Anzahl Nachrichten, Voice-Zeit). Laufende Voice-Sitzungen "
    "liegen nur im Arbeitsspeicher."
)


async def setup(bot):
    await bot.add_cog(ServerStats(bot))
