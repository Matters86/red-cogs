from .streamer import Streamer

__red_end_user_data_statement__ = (
    "Gespeichert werden beobachtete öffentliche Twitch-/YouTube-Kanäle, deren Einstellungen "
    "und die IDs der eigenen Discord-Ankündigungen. Es werden keine Discord-Nutzerprofile angelegt."
)


async def setup(bot):
    await bot.add_cog(Streamer(bot))
