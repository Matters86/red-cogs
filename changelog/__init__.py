from .changelog import Changelog


async def setup(bot):
    await bot.add_cog(Changelog(bot))
