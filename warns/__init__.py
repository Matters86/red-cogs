from .warns import Warns


async def setup(bot):
    await bot.add_cog(Warns(bot))
