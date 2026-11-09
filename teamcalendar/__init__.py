from .teamcalendar import TeamCalendar


async def setup(bot):
    await bot.add_cog(TeamCalendar(bot))
