from .organigram import Organigram


async def setup(bot):
    await bot.add_cog(Organigram(bot))
