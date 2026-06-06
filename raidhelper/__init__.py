from .raidhelper import RaidHelper


async def setup(bot):
    await bot.add_cog(RaidHelper(bot))
