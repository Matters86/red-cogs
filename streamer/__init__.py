from .streamer import Streamer

__red_end_user_data_statement__ = (
    "Gespeichert werden die beobachtete Discord-Rollen-ID, öffentliche Twitch-/YouTube-Kanäle, "
    "Streamtitel, Einstellungen und die IDs der eigenen Discord-Ankündigungen. Aktuelle Discord-Aktivitäten "
    "werden im Speicher ausgewertet; Discord-Mitglieder-IDs und -Anzeigenamen werden dafür nicht in "
    "Ankündigungsdaten gespeichert. Es werden keine Discord-Nutzerprofile angelegt."
)


async def setup(bot):
    await bot.add_cog(Streamer(bot))
