from .twitchlive import TwitchLive

__red_end_user_data_statement__ = (
    "Dieser Cog speichert pro Server die beobachteten Twitch-Kanäle samt Einstellungen und, falls die "
    "Live-Rolle genutzt wird, die vom Team eingetragene Zuordnung Discord-Nutzer-ID ↔ Twitch-Login. "
    "Diese Zuordnung wird bei einer Datenlöschanfrage entfernt."
)


async def setup(bot):
    await bot.add_cog(TwitchLive(bot))
