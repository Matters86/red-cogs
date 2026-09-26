from .levels import Levels

__red_end_user_data_statement__ = (
    "Dieser Cog speichert pro Server und Mitglied die XP, das Level und den Zeitpunkt der letzten "
    "XP-Nachricht (für den Cooldown). Nachrichteninhalte werden nicht gespeichert. Avatare werden nur "
    "kurz im Arbeitsspeicher zwischengespeichert, um die Rangkarte zu erzeugen. Die Daten lassen sich "
    "über Reds Datenlöschung entfernen."
)


async def setup(bot):
    await bot.add_cog(Levels(bot))
